"""Команда /initiative: субъектность — насколько бот пишет по своей инициативе.

Отдельный от пульса (/heartbeat) параметр: 0–100%. 0 — никогда не пишет первым,
выше — чаще и спонтаннее. Пульс задаёт, как часто бот «думает»; initiative —
шанс, что мысль обернётся сообщением. Менять: в личке владелец, в группе админ.
"""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserRole, Workspace, WorkspaceType
from app.services import audit, heartbeat, messages

router = Router(name="initiative")


def _can_change(user: User, workspace: Workspace) -> bool:
    return user.role == UserRole.admin or workspace.type == WorkspaceType.personal


def _describe(percent: int) -> str:
    if percent <= 0:
        return "0% — сам писать не буду, только когда позовёшь. 🤐"
    if percent < 34:
        return f"{percent}% — пишу редко и только по делу. 🌱"
    if percent < 67:
        return f"{percent}% — иногда по реальному поводу, изредка чек-ин. 🙂"
    return f"{percent}% — заходи-болтаю, могу и просто поинтересоваться. 🗣"


@router.message(Command("initiative"))
async def cmd_initiative(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    arg = (command.args or "").strip().rstrip("%")
    current = heartbeat.initiative_percent(workspace)

    if not arg:
        text = (
            f"🎭 <b>Моя инициативность: {_describe(current)}</b>\n"
            "Насколько я сам завожу разговор (отдельно от пульса /heartbeat).\n\n"
            "Изменить: <code>/initiative 0</code>…<code>100</code>\n"
            "0 — вообще не писать первым; 30 — изредка; 80 — часто."
        )
        sent = await message.answer(text)
        await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
        return

    if not _can_change(user, workspace):
        text = "Настраивать инициативность может только админ. 🙅"
        sent = await message.answer(text)
        await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
        return

    if not arg.isdigit():
        text = "Формат: <code>/initiative 30</code> (0–100%). 0 — не писать первым."
        sent = await message.answer(text)
        await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
        return

    value = max(0, min(100, int(arg)))
    workspace.settings = {**(workspace.settings or {}), "initiative": value}
    await audit.log(
        session,
        action="initiative_set",
        payload={"initiative": value},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    text = f"🎭 Инициативность: <b>{_describe(value)}</b>"
    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
