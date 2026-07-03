from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, Workspace
from app.services import audit, messages

router = Router(name="persona")


class PersonaSetup(StatesGroup):
    waiting = State()


async def _set_persona(
    session: AsyncSession, workspace: Workspace, user: User, text: str
) -> None:
    # JSONB: пересоздаём dict, чтобы SQLAlchemy увидел изменение
    workspace.settings = {**(workspace.settings or {}), "persona": text.strip()}
    await audit.log(
        session,
        action="persona_set",
        payload={"persona": text.strip()[:500]},
        workspace_id=workspace.id,
        user_id=user.id,
    )


async def _reply_and_save(
    message: Message, session: AsyncSession, workspace: Workspace, text: str
) -> None:
    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)


@router.message(PersonaSetup.waiting, F.text & ~F.text.startswith("/"))
async def persona_from_onboarding(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await _set_persona(session, workspace, user, message.text)
    await state.clear()
    await _reply_and_save(
        message,
        session,
        workspace,
        "Принято! Таким и буду в этом чате. 🎭\n"
        "Посмотреть или поменять: /persona",
    )


@router.message(Command("persona"))
async def cmd_persona(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
    state: FSMContext,
) -> None:
    if command.args:
        await _set_persona(session, workspace, user, command.args)
        await state.clear()
        await _reply_and_save(message, session, workspace, "Обновил характер для этого чата. 🎭")
        return

    persona = (workspace.settings or {}).get("persona")
    if persona:
        text = (
            f"Мой характер в этом чате:\n<i>{persona}</i>\n\n"
            "Поменять: <code>/persona новое описание</code>"
        )
    else:
        text = (
            "Характер для этого чата ещё не задан — работаю по умолчанию "
            "(дружелюбный и слегка ироничный).\n"
            "Задать: <code>/persona описание</code>"
        )
    await _reply_and_save(message, session, workspace, text)
