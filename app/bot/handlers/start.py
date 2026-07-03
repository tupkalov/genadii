from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.persona import PersonaSetup
from app.db.models import User, Workspace
from app.services import messages

router = Router(name="start")

GREETING = (
    "Привет, {name}! Я — <b>Умный Геннадий</b> 🧠\n\n"
    "Бот для своих: общаюсь, помню контекст чата, считаю расходы.\n\n"
    "Команды:\n"
    "• /whoami — кто ты для меня\n"
    "• /persona — мой характер в этом чате\n"
    "• /memory — что я помню (забыть: /forget)\n"
    "• /tasks — напоминания и отложенные задачи\n"
    "• /tools — мои инструменты\n"
    "• /model — какая модель думает за меня\n"
    "• /stats — расходы этого чата\n"
    "• /budget — месячный лимит расходов"
)

PERSONA_PROMPT = (
    "\n\n🎭 <b>Кстати, каким мне быть в этом чате?</b>\n"
    "Опиши следующим сообщением (например: «саркастичный кот-эрудит» или "
    "«строгий деловой ассистент») — или просто продолжай, останусь собой."
)


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    text = GREETING.format(name=user.first_name or user.username or "друг")
    if not (workspace.settings or {}).get("persona"):
        text += PERSONA_PROMPT
        await state.set_state(PersonaSetup.waiting)
    sent = await message.answer(text)
    await messages.save_assistant(
        session, workspace, text, tg_message_id=sent.message_id
    )
