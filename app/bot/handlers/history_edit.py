from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.chat import _generate_and_send
from app.config import get_settings
from app.db.models import User, Workspace
from app.services import audit, messages

router = Router(name="history_edit")


@router.message(Command("undo"))
async def cmd_undo(
    message: Message, user: User, workspace: Workspace, session: AsyncSession
) -> None:
    """Стирает из истории последний обмен (ход юзера + мой ответ) —
    как будто его не было."""
    await messages.drop_command_row(session, workspace, message.message_id)
    deleted = await messages.delete_last_exchange(session, workspace)
    if not deleted:
        await message.answer("Отменять нечего — свежих обменов в истории нет. 🤷")
        return
    await audit.log(
        session,
        action="history_undo",
        payload={"deleted_rows": deleted},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    await message.answer(
        "🗑 Стёр последний обмен из истории — в контексте его больше нет.\n"
        "(Сами сообщения в Telegram остаются — их я удалять не умею.)"
    )


@router.message(Command("retry"))
async def cmd_retry(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    """Перегенерирует последний ответ. «/retry smart» — разово умной моделью."""
    force_model = None
    arg = (command.args or "").strip().lower()
    if arg == "smart":
        force_model = get_settings().smart_model
    elif arg:
        await message.answer(
            "Понимаю только <code>/retry</code> или <code>/retry smart</code>."
        )
        return

    await messages.drop_command_row(session, workspace, message.message_id)
    deleted = await messages.delete_trailing_assistant(session, workspace)
    if deleted is None:
        await message.answer("Перегенерировать нечего — в истории нет твоих сообщений. 🤷")
        return
    await audit.log(
        session,
        action="history_retry",
        payload={"deleted_rows": deleted, "force_model": force_model},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    await _generate_and_send(message, user, workspace, session, force_model=force_model)
