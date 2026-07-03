from fastapi import APIRouter, Query
from sqlalchemy import select

from app.db.models import AuditLog
from app.db.session import session_factory

router = APIRouter(prefix="/logs")


@router.get("/audit")
async def audit_logs(
    workspace_id: int | None = None,
    action: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    """Аудит: доступы, tool-вызовы, инвайты, смены настроек."""
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if workspace_id is not None:
        query = query.where(AuditLog.workspace_id == workspace_id)
    if action:
        query = query.where(AuditLog.action == action)

    async with session_factory() as session:
        rows = (await session.execute(query)).scalars().all()

    return {
        "entries": [
            {
                "id": r.id,
                "action": r.action,
                "workspace_id": r.workspace_id,
                "user_id": r.user_id,
                "payload": r.payload,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }
