from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message

from app.config import get_settings
from app.db.models import UserRole
from app.services import audit, users

DENIED_TEXT = (
    "Извини, я — Умный Геннадий, закрытый бот для своих. "
    "Попроси владельца добавить тебя: передай ему свой ID — <code>{tg_id}</code>."
)


class AuthMiddleware(BaseMiddleware):
    """Whitelist в БД: незнакомцев не пускаем, попытку логируем в audit_log."""

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return None

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
                    "chat_id": event.chat.id,
                    "chat_type": event.chat.type,
                },
            )
            # В группах молчим, чтобы не спамить; в личке вежливо отказываем
            if event.chat.type == "private":
                await event.answer(DENIED_TEXT.format(tg_id=tg_user.id))
            return None

        users.sync_profile(user, tg_user)
        data["user"] = user
        return await handler(event, data)
