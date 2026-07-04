import html

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, Workspace
from app.services import messages

router = Router(name="whoami")


@router.message(Command("whoami"))
async def cmd_whoami(
    message: Message, user: User, workspace: Workspace, session: AsyncSession
) -> None:
    text = (
        "<b>Ты:</b>\n"
        f"• tg_id: <code>{user.tg_id}</code>\n"
        f"• username: @{html.escape(user.username or '—')}\n"
        f"• роль: <b>{user.role.value}</b>\n"
        f"• в whitelist с: {user.created_at:%Y-%m-%d}\n\n"
        "<b>Workspace:</b>\n"
        f"• id: <code>{workspace.id}</code>\n"
        f"• тип: <b>{workspace.type.value}</b>\n"
        f"• название: {html.escape(workspace.title or '—')}\n"
        f"• tg_chat_id: <code>{workspace.tg_chat_id}</code>"
    )
    sent = await message.answer(text)
    await messages.save_assistant(
        session, workspace, text, tg_message_id=sent.message_id
    )
