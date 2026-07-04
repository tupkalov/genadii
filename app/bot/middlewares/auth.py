from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

from app.config import get_settings
from app.db.models import UserRole
from app.services import audit, users

DENIED_TEXT = (
    "Извини, я — Умный Геннадий, закрытый бот для своих. "
    "Попроси владельца добавить тебя: передай ему свой ID — <code>{tg_id}</code>."
)


class AuthMiddleware(BaseMiddleware):
    """Whitelist в БД: незнакомцев не пускаем, попытку логируем в audit_log.

    Событийно-агностична (Message, CallbackQuery, ...) — чат берём из
    data["event_chat"], который aiogram кладёт для всех типов апдейтов.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return None

        chat = data.get("event_chat")
        session = data["session"]
        user = await users.get_by_tg_id(session, tg_user.id)

        # Бутстрап на лету: админ из env пишет боту впервые
        if user is None and tg_user.id in get_settings().admin_ids:
            user = await users.create_from_tg(session, tg_user, role=UserRole.admin)

        if user is None or not user.is_active:
            await audit.log(
                session,
                action="access_denied",
                payload={
                    "tg_id": tg_user.id,
                    "username": tg_user.username,
                    "chat_id": chat.id if chat else None,
                    "chat_type": chat.type if chat else None,
                },
            )
            if isinstance(event, CallbackQuery):
                # Тост показывает HTML буквально — только plain text
                await event.answer("Нет доступа 🙅", show_alert=True)
            elif chat is not None and chat.type == "private":
                # В группах молчим, чтобы не спамить; в личке вежливо отказываем
                await event.answer(DENIED_TEXT.format(tg_id=tg_user.id))
            return None

        users.sync_profile(user, tg_user)
        data["user"] = user
        return await handler(event, data)
