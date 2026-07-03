import html

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SavedScript, User, Workspace
from app.services import audit, messages

router = Router(name="scripts")


@router.message(Command("scripts"))
async def cmd_scripts(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    args = (command.args or "").split()

    if len(args) == 2 and args[0] in ("show", "delete"):
        name = args[1].lower()
        script = await session.scalar(
            select(SavedScript).where(
                SavedScript.workspace_id == workspace.id, SavedScript.name == name
            )
        )
        if script is None:
            text = f"Скрипта «{html.escape(name)}» в этом чате нет."
        elif args[0] == "show":
            text = (
                f"<b>{script.name}</b> — {html.escape(script.description or 'без описания')}\n"
                f"<pre>{html.escape(script.code[:3000])}</pre>"
            )
        else:
            await session.execute(
                delete(SavedScript).where(SavedScript.id == script.id)
            )
            await audit.log(
                session,
                action="script_deleted",
                payload={"name": script.name},
                workspace_id=workspace.id,
                user_id=user.id,
            )
            text = f"Скрипт «{script.name}» удалён. 🗑"
    else:
        scripts = (
            await session.scalars(
                select(SavedScript)
                .where(SavedScript.workspace_id == workspace.id)
                .order_by(SavedScript.name)
            )
        ).all()
        if scripts:
            text = "<b>Сохранённые скрипты:</b>\n" + "\n".join(
                f"• <code>{s.name}</code> — {html.escape(s.description or 'без описания')}"
                for s in scripts
            )
            text += (
                "\n\n<code>/scripts show имя</code> | <code>/scripts delete имя</code>\n"
                "Запуск: попроси меня «запусти имя»."
            )
        else:
            text = (
                "Сохранённых скриптов нет. Навайбкодь что-нибудь со мной "
                "и скажи «сохрани как ...» (нужны включённые tools: "
                "<code>/tools enable run_python</code> и <code>save_script</code>)."
            )

    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
