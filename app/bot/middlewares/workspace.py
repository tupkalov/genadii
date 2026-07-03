from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message

from app.services import messages, workspaces


class WorkspaceMiddleware(BaseMiddleware):
    """Резолвит workspace по чату и сохраняет входящее сообщение."""

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        session = data["session"]
        user = data["user"]

        workspace = await workspaces.resolve(session, event.chat, user)
        data["workspace"] = workspace

        await messages.save_incoming(session, workspace, user, event)

        return await handler(event, data)
