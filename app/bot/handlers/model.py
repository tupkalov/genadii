import html

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import User, UserRole, Workspace
from app.services import audit, messages
from app.services.llm_chat import pick_model

router = Router(name="model")

# Подборка проверенных моделей OpenRouter под этого бота. Можно задать ЛЮБУЮ
# (аргумент /model принимает любой vendor/model-name) — это просто ориентир.
# Порядок: от дешёвой/слабой к умной/дорогой. Цены — за 1M токенов
# (вход/выход), OpenRouter, актуальны на 2026-07; могут меняться.
RECOMMENDED_MODELS = [
    ("google/gemini-2.5-flash-lite", "дёшево ($0.10/$0.40), но слабо в инструментах — врёт и откладывает"),
    ("google/gemini-2.5-flash", "⭐ умнее, надёжно вызывает инструменты ($0.30/$2.50)"),
    ("deepseek/deepseek-chat", "дёшево, приличный агент, но помедленнее"),
    ("google/gemini-2.5-pro", "заметно умнее, дороже — для сложных задач"),
    ("anthropic/claude-haiku-4.5", "быстрая и умная, средняя цена"),
]


def _models_list_text(default_model: str) -> str:
    lines = ["<b>Модели-ориентиры</b> (можно указать любую с OpenRouter):", ""]
    for model_id, note in RECOMMENDED_MODELS:
        mark = " — <i>текущий дефолт</i>" if model_id == default_model else ""
        lines.append(f"• <code>{html.escape(model_id)}</code>{mark}\n  {note}")
    lines += [
        "",
        "Сменить (только админ): <code>/model google/gemini-2.5-flash</code>",
        "Вернуть дефолт: <code>/model reset</code>",
    ]
    return "\n".join(lines)


@router.message(Command("model"))
async def cmd_model(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    settings = get_settings()

    if command.args and command.args.strip().lower() == "list":
        # Список — безобидная справка, доступен всем участникам
        text = _models_list_text(settings.default_model)
    elif not command.args:
        current = pick_model(workspace)
        override = (workspace.settings or {}).get("model_override")
        text = (
            f"Модель этого чата: <code>{html.escape(current)}</code>"
            + ("" if override else " (дефолт)")
            + f"\nДефолт: <code>{settings.default_model}</code>\n\n"
            "Список моделей: <code>/model list</code>\n"
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
            text = (
                "Теперь этот чат думает через "
                f"<code>{html.escape(command.args.strip())}</code>"
            )
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
