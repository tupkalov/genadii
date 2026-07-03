from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import User, UserRole, Workspace
from app.services import audit, messages
from app.services.llm_chat import pick_model

router = Router(name="model")


@router.message(Command("model"))
async def cmd_model(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    settings = get_settings()

    if not command.args:
        current = pick_model(workspace)
        override = (workspace.settings or {}).get("model_override")
        text = (
            f"Модель этого чата: <code>{current}</code>"
            + ("" if override else " (дефолт)")
            + f"\nДефолт: <code>{settings.default_model}</code>\n\n"
            "Сменить (только админ): <code>/model vendor/model-name</code>\n"
            "Вернуть дефолт: <code>/model reset</code>"
        )
    elif user.role != UserRole.admin:
        text = "Менять модель может только админ. 🙅"
    else:
        new_settings = dict(workspace.settings or {})
        if command.args.strip().lower() == "reset":
            new_settings.pop("model_override", None)
            text = f"Вернул дефолтную модель: <code>{settings.default_model}</code>"
        else:
            new_settings["model_override"] = command.args.strip()
            text = f"Теперь этот чат думает через <code>{command.args.strip()}</code>"
        workspace.settings = new_settings
        await audit.log(
            session,
            action="model_set",
            payload={"model": new_settings.get("model_override")},
            workspace_id=workspace.id,
            user_id=user.id,
        )

    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
