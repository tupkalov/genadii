from aiogram.types import Chat
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, Workspace, WorkspaceMember, WorkspaceType


async def resolve(session: AsyncSession, chat: Chat, user: User) -> Workspace:
    """Находит или создаёт workspace для чата и гарантирует членство user'а.

    Апдейты обрабатываются конкурентно, поэтому создание — через
    INSERT ... ON CONFLICT DO NOTHING + повторный SELECT (см. уникальный
    индекс по tg_chat_id).
    """
    workspace = await session.scalar(
        select(Workspace).where(Workspace.tg_chat_id == chat.id)
    )
    if workspace is None:
        if chat.type == "private":
            ws_type = WorkspaceType.personal
            title = user.username or user.first_name or f"user-{user.tg_id}"
        else:
            ws_type = WorkspaceType.group
            title = chat.title or f"group-{chat.id}"
        await session.execute(
            pg_insert(Workspace)
            .values(type=ws_type, tg_chat_id=chat.id, title=title, settings={})
            .on_conflict_do_nothing(index_elements=["tg_chat_id"])
        )
        workspace = await session.scalar(
            select(Workspace).where(Workspace.tg_chat_id == chat.id)
        )

    await session.execute(
        pg_insert(WorkspaceMember)
        .values(workspace_id=workspace.id, user_id=user.id)
        .on_conflict_do_nothing(index_elements=["workspace_id", "user_id"])
    )
    return workspace
