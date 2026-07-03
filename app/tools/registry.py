from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, Workspace


@dataclass
class ToolContext:
    session: AsyncSession
    workspace: Workspace
    user: User
    # Файлы, которые tools хотят отправить в чат вместе с ответом
    attachments: list[bytes] = field(default_factory=list)
    # Для tools, которым нужен доступ к Telegram (реакции): заполняется в чат-хендлере
    bot: object | None = None
    chat_id: int | None = None
    target_message_id: int | None = None


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema аргументов
    handler: Callable[..., Awaitable[str]]  # async (ctx, **kwargs) -> str
    default_enabled: bool = False  # включён ли без явного permission'а
    hourly_limit: int | None = None  # лимит вызовов на пользователя в час (дорогие tools)

    def to_openrouter(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    TOOLS[tool.name] = tool
    return tool
