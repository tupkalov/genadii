"""Служебные апдейты: миграция группы в супергруппу, правки сообщений."""
import logging

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, Workspace
from app.services import messages, workspaces

logger = logging.getLogger("gennady.service")

# message-роутер: миграция чата
message_router = Router(name="service")
# edited_message-роутер: правки
edited_router = Router(name="edited")


@message_router.message(F.migrate_to_chat_id)
async def on_migrate(message: Message, session: AsyncSession, **_: object) -> None:
    new_id = message.migrate_to_chat_id
    moved = await workspaces.migrate_chat_id(session, message.chat.id, new_id)
    logger.info(
        "Миграция чата %s -> %s: %s",
        message.chat.id,
        new_id,
        "перенесён" if moved else "пропущен (нет workspace или конфликт)",
    )


@edited_router.edited_message()
async def on_edited(
    message: Message, user: User, workspace: Workspace, session: AsyncSession
) -> None:
    await messages.update_edited(session, workspace, message)
