from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import get_settings
from app.db.models import Message, MessageRole, User
from app.tools.registry import Tool, ToolContext, register

MAX_MESSAGES = 300
TOTAL_CHARS_LIMIT = 12_000
PER_MESSAGE_LIMIT = 300


async def _read_chat_history(
    ctx: ToolContext, since_hours: float = 24, limit: int = 100
) -> str:
    limit = min(int(limit), MAX_MESSAGES)
    since = datetime.now(timezone.utc) - timedelta(hours=float(since_hours))
    tz = ZoneInfo(get_settings().timezone)

    rows = (
        await ctx.session.execute(
            select(Message, User.first_name, User.username)
            .outerjoin(User, Message.user_id == User.id)
            .where(
                Message.workspace_id == ctx.workspace.id,
                Message.created_at >= since,
                Message.role.in_([MessageRole.user, MessageRole.assistant]),
            )
            .order_by(Message.id.desc())
            .limit(limit)
        )
    ).all()

    if not rows:
        return "За этот период сообщений не было."

    lines = []
    for msg, first_name, username in reversed(rows):
        author = first_name or username or "Геннадий"
        stamp = msg.created_at.astimezone(tz).strftime("%d.%m %H:%M")
        lines.append(f"[{stamp}] {author}: {msg.content[:PER_MESSAGE_LIMIT]}")

    text = "\n".join(lines)
    if len(text) > TOTAL_CHARS_LIMIT:
        text = "…(обрезано)\n" + text[-TOTAL_CHARS_LIMIT:]
    return text


register(
    Tool(
        name="read_chat_history",
        description=(
            "Прочитать историю этого чата глубже, чем видно в контексте. "
            "Используй для «что я пропустил», сводок дня и вопросов о прошлых "
            "обсуждениях. Возвращает сообщения с авторами и временем."
        ),
        parameters={
            "type": "object",
            "properties": {
                "since_hours": {
                    "type": "number",
                    "description": "За сколько последних часов взять сообщения (по умолчанию 24)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Максимум сообщений (по умолчанию 100, максимум 300)",
                },
            },
        },
        handler=_read_chat_history,
        default_enabled=True,
    )
)
