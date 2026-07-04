import html

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, Workspace
from app.services import audit, memory, messages

router = Router(name="memory")


@router.message(Command("memory"))
async def cmd_memory(
    message: Message, user: User, workspace: Workspace, session: AsyncSession
) -> None:
    facts = await memory.list_facts(session, workspace, limit=50)
    if facts:
        text = "<b>Что я помню в этом чате:</b>\n" + "\n".join(
            f"• <code>#{f.id}</code> {html.escape(f.content)}" for f in reversed(facts)
        )
        text += "\n\nЗабыть: <code>/forget номер</code>"
    else:
        text = "Пока ничего не запомнил. Скажи «запомни: ...» — и запомню."
    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)


@router.message(Command("forget"))
async def cmd_forget(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    arg = (command.args or "").strip().lstrip("#")
    if not arg.isdigit():
        text = "Формат: <code>/forget номер</code> (номера — в /memory)"
    else:
        entry = await memory.archive_fact(session, workspace, int(arg))
        if entry is None:
            text = f"Факта #{arg} в этом чате нет."
        else:
            text = f"Забыл: «{html.escape(entry.content)}» 🗑"
            await audit.log(
                session,
                action="memory_forget",
                payload={"fact_id": entry.id, "content": entry.content[:200]},
                workspace_id=workspace.id,
                user_id=user.id,
            )
    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
