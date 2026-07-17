import html

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import User, UserRole, Workspace
from app.services import app_settings, audit, messages
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
    # Эффективный глобальный дефолт: БД (задан админом) или конфиг/.env
    default = await app_settings.default_model(session)
    args = (command.args or "").strip()
    low = args.lower()

    if low == "list":
        # Список — безобидная справка, доступен всем участникам
        text = _models_list_text(default)
    elif low == "default" or low.startswith("default "):
        # Глобальный дефолт на ВСЕ чаты без своего оверрайда
        rest = args[len("default"):].strip()
        if not rest:
            text = (
                f"🌍 <b>Глобальный дефолт модели:</b> <code>{html.escape(default)}</code>\n"
                f"(из конфига: <code>{settings.default_model}</code>)\n\n"
                "Сменить на все чаты (админ): <code>/model default vendor/model</code>\n"
                "Вернуть к конфигу: <code>/model default reset</code>"
            )
        elif user.role != UserRole.admin:
            text = "Глобальный дефолт может менять только админ. 🙅"
        elif rest.lower() == "reset":
            await app_settings.reset_default_model(session)
            text = (
                "🌍 Глобальный дефолт сброшен к конфигу: "
                f"<code>{html.escape(settings.default_model)}</code>"
            )
            await audit.log(
                session, action="model_default_reset",
                payload={"model": settings.default_model}, user_id=user.id,
            )
        else:
            await app_settings.set_default_model(session, rest)
            text = (
                f"🌍 Глобальный дефолт для всех чатов: <code>{html.escape(rest)}</code>\n"
                "Чаты со своим <code>/model …</code> не затронуты."
            )
            await audit.log(
                session, action="model_default_set",
                payload={"model": rest}, user_id=user.id,
            )
    elif not args:
        current = pick_model(workspace, default_model=default)
        override = (workspace.settings or {}).get("model_override")
        text = (
            f"Модель этого чата: <code>{html.escape(current)}</code>"
            + ("" if override else " (дефолт)")
            + f"\nДефолт: <code>{html.escape(default)}</code>\n\n"
            "Список моделей: <code>/model list</code>\n"
            "Сменить в этом чате (админ): <code>/model vendor/model-name</code>\n"
            "На все чаты (админ): <code>/model default vendor/model-name</code>\n"
            "Вернуть дефолт: <code>/model reset</code>"
        )
    elif user.role != UserRole.admin:
        text = "Менять модель может только админ. 🙅"
    else:
        new_settings = dict(workspace.settings or {})
        if low == "reset":
            new_settings.pop("model_override", None)
            text = f"Вернул дефолтную модель: <code>{html.escape(default)}</code>"
        else:
            new_settings["model_override"] = args
            text = f"Теперь этот чат думает через <code>{html.escape(args)}</code>"
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
