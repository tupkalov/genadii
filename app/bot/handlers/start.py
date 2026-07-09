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
    "Бот для своих: общаюсь, помню контекст, выполняю код, хожу в интернет "
    "и подключаюсь к внешним сервисам.\n\n"
    "Главное:\n"
    "• /memory — что я помню (забыть: /forget)\n"
    "• /tasks — напоминания и отложенные задачи\n"
    "• /skill — сценарии чата (запуск: /имя-скилла)\n"
    "• /mcp — подключение внешних сервисов (MCP)\n"
    "• /hook — входящие вебхуки\n"
    "• /search — поиск по памяти и переписке\n"
    "• /undo и /retry — стереть/перегенерировать последний ответ\n"
    "• /persona, /model, /tools, /stats, /budget — настройки и расходы\n\n"
    "Спроси «что ты умеешь?» — расскажу подробно про всё."
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
