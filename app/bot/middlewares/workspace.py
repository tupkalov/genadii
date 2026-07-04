from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.services import messages, workspaces


class WorkspaceMiddleware(BaseMiddleware):
    """Резолвит workspace по чату и сохраняет входящее сообщение.

    Работает и для callback_query: чат берём из data["event_chat"],
    сохраняем в историю только настоящие Message.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session = data["session"]
        user = data["user"]

        chat = data.get("event_chat")
        if chat is None:
            # callback от недоступного (старого) сообщения — workspace не определить
            if isinstance(event, CallbackQuery):
                await event.answer("Сообщение устарело", show_alert=False)
            return None

        workspace = await workspaces.resolve(session, chat, user)
        data["workspace"] = workspace

        # edited_message приходит сюда же — его не сохраняем как новое,
        # обновлением занимается отдельный хендлер
        if isinstance(event, Message) and not data.get("_skip_save"):
            await messages.save_incoming(session, workspace, user, event)

        return await handler(event, data)
