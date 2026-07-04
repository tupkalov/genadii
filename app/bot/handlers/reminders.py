import html

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, Workspace
from app.services import audit, messages, reminders

router = Router(name="reminders")

KIND_ICONS = {"reminder": "⏰", "agent_task": "🤖"}


@router.message(Command("tasks", "reminders"))
async def cmd_tasks(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    args = (command.args or "").split()

    if len(args) == 2 and args[0] == "cancel" and args[1].lstrip("#").isdigit():
        task = await reminders.cancel(session, workspace, int(args[1].lstrip("#")))
        if task is None:
            text = "Такой активной задачи в этом чате нет."
        else:
            text = f"Отменил #{task.id}: {html.escape((task.payload or {}).get('text', ''))}"
            await audit.log(
                session,
                action="task_cancelled",
                payload={"task_id": task.id, "kind": task.kind},
                workspace_id=workspace.id,
                user_id=user.id,
            )
    else:
        pending = await reminders.list_pending(session, workspace)
        if pending:
            lines = []
            for t in pending:
                icon = KIND_ICONS.get(t.kind, "❔")
                when = reminders.format_local(t.run_at)
                if t.cron:
                    when += f" (cron: {t.cron})"
                lines.append(
                    f"• {icon} <code>#{t.id}</code> {html.escape(when)} — "
                    f"{html.escape((t.payload or {}).get('text', ''))}"
                )
            text = (
                "<b>Запланировано (⏰ напоминание / 🤖 задача):</b>\n"
                + "\n".join(lines)
                + "\n\nОтменить: <code>/tasks cancel номер</code>"
            )
        else:
            text = (
                "Ничего не запланировано. Скажи «напомни …» или "
                "«сделай завтра в 9 …» — и заведу."
            )

    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
