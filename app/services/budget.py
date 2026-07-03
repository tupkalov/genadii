from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import LlmUsage, Workspace


def get_limit(workspace: Workspace) -> float | None:
    """Лимит месяца: настройка workspace -> дефолт из env. 0/None = без лимита."""
    value = (workspace.settings or {}).get("monthly_budget_usd")
    if value is None:
        value = get_settings().default_monthly_budget_usd
    return float(value) if value else None


async def month_spend(session: AsyncSession, workspace: Workspace) -> float:
    start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    total = await session.scalar(
        select(func.coalesce(func.sum(LlmUsage.cost_usd), 0)).where(
            LlmUsage.workspace_id == workspace.id,
            LlmUsage.created_at >= start,
        )
    )
    return float(total)


async def check(
    session: AsyncSession, workspace: Workspace
) -> tuple[bool, float, float | None]:
    """(исчерпан ли лимит, потрачено за месяц, лимит)."""
    limit = get_limit(workspace)
    spend = await month_spend(session, workspace)
    return (limit is not None and spend >= limit), spend, limit
