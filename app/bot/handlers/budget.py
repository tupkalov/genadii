from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserRole, Workspace
from app.services import audit, budget, messages

router = Router(name="budget")


@router.message(Command("budget"))
async def cmd_budget(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    arg = (command.args or "").strip().replace(",", ".").lower()

    if arg:
        if user.role != UserRole.admin:
            text = "Менять бюджет может только админ. 🙅"
        else:
            if arg in ("off", "0"):
                value = 0.0
            else:
                try:
                    value = float(arg)
                    if value < 0:
                        raise ValueError
                except ValueError:
                    value = None
            if value is None:
                text = "Формат: <code>/budget 5</code> ($/мес) или <code>/budget off</code>"
            else:
                workspace.settings = {
                    **(workspace.settings or {}),
                    "monthly_budget_usd": value,
                }
                await audit.log(
                    session,
                    action="budget_set",
                    payload={"monthly_budget_usd": value},
                    workspace_id=workspace.id,
                    user_id=user.id,
                )
                text = (
                    f"Лимит этого чата: ${value:.2f}/мес"
                    if value
                    else "Лимит снят — жгите. 🔥"
                )
    else:
        over, spend, limit = await budget.check(session, workspace)
        limit_text = f"${limit:.2f}" if limit else "не задан"
        text = (
            f"💰 <b>Бюджет чата (текущий месяц)</b>\n"
            f"• потрачено: ${spend:.4f}\n"
            f"• лимит: {limit_text}"
        )
        if over:
            text += "\n\n⛔ Лимит исчерпан — я молчу до нового месяца или поднятия лимита."
        text += "\n\nАдмин: <code>/budget 5</code> или <code>/budget off</code>"

    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
