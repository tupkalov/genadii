from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.db.models import LlmUsage, Workspace
from app.db.session import session_factory

router = APIRouter(prefix="/stats")


@router.get("/usage")
async def usage_by_workspace(days: int | None = Query(default=None, ge=1)) -> dict:
    """Расход LLM по каждому workspace: вызовы, токены, стоимость."""
    query = (
        select(
            Workspace.id,
            Workspace.type,
            Workspace.title,
            func.count(LlmUsage.id).label("calls"),
            func.coalesce(func.sum(LlmUsage.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(LlmUsage.completion_tokens), 0).label(
                "completion_tokens"
            ),
            func.coalesce(func.sum(LlmUsage.cost_usd), 0).label("cost_usd"),
        )
        .join(LlmUsage, LlmUsage.workspace_id == Workspace.id)
        .group_by(Workspace.id)
        .order_by(func.sum(LlmUsage.cost_usd).desc())
    )
    if days:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        query = query.where(LlmUsage.created_at >= since)

    async with session_factory() as session:
        rows = (await session.execute(query)).all()

    workspaces = [
        {
            "workspace_id": r.id,
            "type": r.type.value,
            "title": r.title,
            "calls": r.calls,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "cost_usd": float(r.cost_usd),
        }
        for r in rows
    ]
    return {
        "days": days,
        "total_cost_usd": round(sum(w["cost_usd"] for w in workspaces), 6),
        "workspaces": workspaces,
    }
