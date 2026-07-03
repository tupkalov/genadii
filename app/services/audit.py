from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog


async def log(
    session: AsyncSession,
    action: str,
    payload: dict[str, Any] | None = None,
    workspace_id: int | None = None,
    user_id: int | None = None,
) -> None:
    session.add(
        AuditLog(
            action=action,
            payload=payload or {},
            workspace_id=workspace_id,
            user_id=user_id,
        )
    )
    await session.flush()
