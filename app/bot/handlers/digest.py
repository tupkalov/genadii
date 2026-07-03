import re

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatting import send_rendered
from app.db.models import User, Workspace, WorkspaceType
from app.services import audit, digest, llm_chat, messages

router = Router(name="digest")

TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


@router.message(Command("digest"))
async def cmd_digest(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    if workspace.type != WorkspaceType.personal:
        text = "Дайджест — личная штука. Настрой его в личке со мной: /digest 21:00"
        sent = await message.answer(text)
        await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
        return

    arg = (command.args or "").strip().lower()

    if arg == "now":
        await message.bot.send_chat_action(message.chat.id, "typing")
        text, usages = await digest.build_for_user(session, user)
        if text is None:
            await message.answer("За последние сутки в твоих группах тихо — нечего дайджестить. 🤷")
        else:
            sent = await send_rendered(message.bot, message.chat.id, text)
            await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
            await llm_chat.log_usages(session, workspace, usages)
        return

    if arg in ("off", "0"):
        workspace.settings = {k: v for k, v in (workspace.settings or {}).items() if k != "digest_time"}
        text = "Дайджест выключен. 🔕"
    elif arg:
        m = TIME_RE.match(arg)
        if not m:
            text = "Формат: <code>/digest 21:00</code>, <code>/digest now</code>, <code>/digest off</code>."
        else:
            hhmm = f"{int(m.group(1)):02d}:{m.group(2)}"
            workspace.settings = {**(workspace.settings or {}), "digest_time": hhmm}
            await audit.log(
                session, action="digest_set", payload={"time": hhmm},
                workspace_id=workspace.id, user_id=user.id,
            )
            text = f"Буду присылать дайджест твоих групп каждый день в <b>{hhmm}</b>. 🌅"
    else:
        current = (workspace.settings or {}).get("digest_time")
        text = (
            (f"🌅 Дайджест включён на <b>{current}</b>.\n" if current else "🌅 Дайджест выключен.\n")
            + "\n<code>/digest 21:00</code> — время, <code>/digest now</code> — прислать сейчас, "
            "<code>/digest off</code> — выключить."
        )

    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
