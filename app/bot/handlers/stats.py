from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LlmUsage, User, Workspace
from app.services import messages

router = Router(name="stats")


@router.message(Command("stats"))
async def cmd_stats(
    message: Message, user: User, workspace: Workspace, session: AsyncSession
) -> None:
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    total = (
        await session.execute(
            select(
                func.count(LlmUsage.id),
                func.coalesce(func.sum(LlmUsage.cost_usd), 0),
                func.coalesce(func.sum(LlmUsage.prompt_tokens), 0),
                func.coalesce(func.sum(LlmUsage.completion_tokens), 0),
            ).where(LlmUsage.workspace_id == workspace.id)
        )
    ).one()
    week = (
        await session.execute(
            select(func.coalesce(func.sum(LlmUsage.cost_usd), 0)).where(
                LlmUsage.workspace_id == workspace.id,
                LlmUsage.created_at >= week_ago,
            )
        )
    ).scalar_one()

    calls, cost_total, p_tokens, c_tokens = total
    text = (
        f"📊 <b>Расходы этого чата</b>\n"
        f"• вызовов LLM: {calls}\n"
        f"• токены: {p_tokens} in / {c_tokens} out\n"
        f"• всего: ${cost_total:.4f}\n"
        f"• за 7 дней: ${week:.4f}"
    )
    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
