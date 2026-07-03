"""Ежедневный дайджест активности групп в личку пользователю."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import (
    LlmUsage,
    Message,
    MessageRole,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceType,
)
from app.llm import client

logger = logging.getLogger("gennady.digest")

MIN_MESSAGES = 3  # если в группе почти тихо — не беспокоим
PER_MESSAGE_LIMIT = 300
BLOCK_LIMIT = 12_000

DIGEST_PROMPT = (
    "Ниже переписка из группового чата «{title}» за последние сутки. Сделай "
    "короткий дружелюбный дайджест для того, кто мог всё пропустить: главные темы, "
    "решения, важное. 4–8 пунктов, без воды.\n\n{block}"
)


async def _group_block(
    session: AsyncSession, workspace: Workspace, since: datetime
) -> tuple[str, int]:
    rows = (
        await session.execute(
            select(Message, User.first_name, User.username)
            .outerjoin(User, Message.user_id == User.id)
            .where(
                Message.workspace_id == workspace.id,
                Message.created_at >= since,
                Message.role == MessageRole.user,
            )
            .order_by(Message.id)
        )
    ).all()
    lines = [
        f"{first_name or username or '—'}: {msg.content[:PER_MESSAGE_LIMIT]}"
        for msg, first_name, username in rows
    ]
    block = "\n".join(lines)
    if len(block) > BLOCK_LIMIT:
        block = block[-BLOCK_LIMIT:]
    return block, len(rows)


async def build_for_user(
    session: AsyncSession, user: User
) -> tuple[str | None, list[client.LlmResult]]:
    """Собирает дайджест по всем группам, где состоит user. Возвращает (текст, usages)."""
    since = datetime.now(timezone.utc) - timedelta(days=1)
    settings = get_settings()

    group_ids = (
        await session.execute(
            select(Workspace.id, Workspace.title)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(
                WorkspaceMember.user_id == user.id,
                Workspace.type == WorkspaceType.group,
            )
        )
    ).all()

    parts: list[str] = []
    usages: list[client.LlmResult] = []
    for ws_id, title in group_ids:
        workspace = await session.get(Workspace, ws_id)
        block, count = await _group_block(session, workspace, since)
        if count < MIN_MESSAGES:
            continue
        result = await client.chat(
            [{"role": "user", "content": DIGEST_PROMPT.format(title=title, block=block)}],
            settings.default_model,
        )
        usages.append(result)
        parts.append(f"📋 <b>{title}</b>\n{result.content.strip()}")

    if not parts:
        return None, usages
    return "🌅 <b>Дайджест за сутки</b>\n\n" + "\n\n".join(parts), usages
