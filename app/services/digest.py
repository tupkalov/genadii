"""Ежедневный дайджест расходов: кто в каком чате сколько потратил.

Содержимое чатов НЕ читается — только агрегаты по llm_usage.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    LlmUsage,
    User,
    UserRole,
    Workspace,
    WorkspaceMember,
    WorkspaceType,
)


async def _visible_workspace_ids(session: AsyncSession, user: User) -> list[int]:
    """Админ видит все чаты, обычный участник — только свои."""
    if user.role == UserRole.admin:
        rows = await session.scalars(select(Workspace.id))
    else:
        rows = await session.scalars(
            select(WorkspaceMember.workspace_id).where(
                WorkspaceMember.user_id == user.id
            )
        )
    return list(rows.all())


async def build_for_user(session: AsyncSession, user: User) -> str | None:
    """Отчёт расходов за 24ч по видимым чатам, с разбивкой по пользователям."""
    since = datetime.now(timezone.utc) - timedelta(days=1)
    ws_ids = await _visible_workspace_ids(session, user)
    if not ws_ids:
        return None

    rows = (
        await session.execute(
            select(
                Workspace.title,
                Workspace.type,
                User.first_name,
                User.username,
                func.sum(LlmUsage.cost_usd),
            )
            .select_from(LlmUsage)
            .join(Workspace, Workspace.id == LlmUsage.workspace_id)
            .outerjoin(User, User.id == LlmUsage.user_id)
            .where(
                LlmUsage.workspace_id.in_(ws_ids),
                LlmUsage.created_at >= since,
            )
            .group_by(Workspace.id, Workspace.type, Workspace.title, User.id)
            .order_by(Workspace.title)
        )
    ).all()

    if not rows:
        return "💸 <b>Расходы за сутки</b>\n\nЗа последние сутки — ноль. Тишина и экономия. 🧘"

    # Группируем по чату: {title: [(who, cost), ...]}
    per_chat: dict[tuple[str, str], list[tuple[str, float]]] = {}
    for title, ws_type, first_name, username, cost in rows:
        key = (title or "—", "👥" if ws_type == WorkspaceType.group else "👤")
        who = first_name or username or "—"
        per_chat.setdefault(key, []).append((who, float(cost or 0)))

    lines: list[str] = ["💸 <b>Расходы за сутки</b>"]
    grand_total = 0.0
    for (title, icon), people in per_chat.items():
        chat_total = sum(c for _, c in people)
        grand_total += chat_total
        lines.append(f"\n{icon} <b>{title}</b> — ${chat_total:.4f}")
        for who, cost in sorted(people, key=lambda x: -x[1]):
            lines.append(f"   • {who}: ${cost:.4f}")

    lines.append(f"\n<b>Итого: ${grand_total:.4f}</b>")
    return "\n".join(lines)
