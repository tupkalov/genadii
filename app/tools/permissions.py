from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ToolPermission, Workspace
from app.tools.registry import TOOLS, Tool


async def enabled_tools(session: AsyncSession, workspace: Workspace) -> list[Tool]:
    """Tools, доступные workspace'у: явный permission или default_enabled."""
    rows = (
        await session.execute(
            select(ToolPermission).where(ToolPermission.workspace_id == workspace.id)
        )
    ).scalars()
    explicit = {row.tool_name: row.enabled for row in rows}
    return [
        tool
        for tool in TOOLS.values()
        if explicit.get(tool.name, tool.default_enabled)
    ]


async def set_permission(
    session: AsyncSession,
    workspace: Workspace,
    tool_name: str,
    enabled: bool,
    granted_by_id: int,
) -> None:
    permission = await session.get(ToolPermission, (workspace.id, tool_name))
    if permission is None:
        permission = ToolPermission(
            workspace_id=workspace.id,
            tool_name=tool_name,
            enabled=enabled,
            granted_by_id=granted_by_id,
        )
        session.add(permission)
    else:
        permission.enabled = enabled
        permission.granted_by_id = granted_by_id
    await session.flush()
