"""Сжатие старой истории чата в сводку — экономия токенов на длинных чатах."""
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import LlmUsage, Message, MessageRole, User, Workspace
from app.llm import client
from app.services import budget

logger = logging.getLogger("gennady.summaries")

BATCH_LIMIT = 200  # сколько сообщений сжимаем за один проход

COMPRESS_PROMPT = (
    "Сожми переписку ниже в сводку до 300 слов: ключевые темы, решения, факты, "
    "договорённости, важные даты. Пиши сжато, без воды.\n\n"
    "{previous}"
    "Переписка:\n{block}"
)


async def compress_workspace(session: AsyncSession, workspace: Workspace) -> bool:
    """Сжимает старую историю workspace, если непокрытых сообщений накопилось
    больше 2×history_limit. Возвращает True, если сжатие произошло."""
    settings = get_settings()
    ws_settings = workspace.settings or {}
    upto_id = ws_settings.get("summary_upto_id", 0)

    uncovered = await session.scalar(
        select(func.count(Message.id)).where(
            Message.workspace_id == workspace.id,
            Message.id > upto_id,
            Message.role.in_([MessageRole.user, MessageRole.assistant]),
        )
    )
    if uncovered <= 2 * settings.history_limit:
        return False

    over, _, _ = await budget.check(session, workspace)
    if over:
        return False

    # Сжимаем всё непокрытое, кроме последних history_limit (они и так в контексте)
    rows = (
        await session.execute(
            select(Message, User.first_name, User.username)
            .outerjoin(User, Message.user_id == User.id)
            .where(
                Message.workspace_id == workspace.id,
                Message.id > upto_id,
                Message.role.in_([MessageRole.user, MessageRole.assistant]),
            )
            .order_by(Message.id)
            .limit(min(uncovered - settings.history_limit, BATCH_LIMIT))
        )
    ).all()
    if not rows:
        return False

    block = "\n".join(
        f"{first_name or username or 'Геннадий'}: {msg.content[:400]}"
        for msg, first_name, username in rows
    )
    previous = ws_settings.get("history_summary")
    prompt = COMPRESS_PROMPT.format(
        previous=(
            f"Прежняя сводка (объедини с новым содержимым):\n{previous}\n\n"
            if previous
            else ""
        ),
        block=block,
    )

    result = await client.chat(
        [{"role": "user", "content": prompt}], settings.default_model
    )

    workspace.settings = {
        **ws_settings,
        "history_summary": result.content.strip()[:6000],
        "summary_upto_id": rows[-1][0].id,
    }
    session.add(
        LlmUsage(
            workspace_id=workspace.id,
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
        )
    )
    logger.info(
        "Workspace %s: сжато %s сообщений (по id %s)",
        workspace.id,
        len(rows),
        rows[-1][0].id,
    )
    return True
