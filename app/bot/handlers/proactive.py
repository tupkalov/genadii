from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserRole, Workspace, WorkspaceType
from app.services import audit, messages

router = Router(name="proactive")


@router.message(Command("proactive"))
async def cmd_proactive(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    arg = (command.args or "").strip().rstrip("%")
    current = (workspace.settings or {}).get("proactive_percent", 0)

    if arg:
        if user.role != UserRole.admin:
            text = "Настраивать болтливость может только админ. 🙅"
        elif workspace.type != WorkspaceType.group:
            text = "Проактивность работает только в группах."
        else:
            try:
                value = max(0, min(100, int(arg)))
            except ValueError:
                value = None
            if value is None:
                text = "Формат: <code>/proactive 5</code> (0–100%), <code>/proactive 0</code> — выкл."
            else:
                workspace.settings = {
                    **(workspace.settings or {}),
                    "proactive_percent": value,
                }
                await audit.log(
                    session,
                    action="proactive_set",
                    payload={"percent": value},
                    workspace_id=workspace.id,
                    user_id=user.id,
                )
                text = (
                    f"Болтливость: <b>{value}%</b> — иногда буду вставлять свои пять копеек. 🗣"
                    if value
                    else "Проактивность выключена — говорю только когда зовут. 🤐"
                )
    else:
        text = (
            f"🗣 <b>Проактивность этого чата: {current}%</b>\n"
            "С таким шансом я сам вставляю реплику в разговор (не чаще раза в 5 мин).\n\n"
            "Админ: <code>/proactive 5</code> (0–100), <code>/proactive 0</code> — выкл."
        )

    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
