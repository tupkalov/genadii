from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.db.models import Workspace, WorkspaceType

BASE_PROMPT = """Ты — Умный Геннадий, self-hosted Telegram-бот для узкого круга друзей.

Базовые правила:
- Отвечай на языке собеседника (обычно русский).
- Это Telegram: пиши кратко и по делу, без длинных лекций, если не просят подробно.
- Не используй markdown-заголовки; допустимы списки и **жирный** умеренно.
- Если чего-то не знаешь или не умеешь (пока нет инструментов) — честно скажи.
"""

GROUP_ADDON = """
Ты в групповом чате. Сообщения приходят в формате «Имя: текст» — учитывай, кто говорит.
Отвечай тому, кто к тебе обратился.
"""

DEFAULT_PERSONA = (
    "Характер: дружелюбный и слегка ироничный умный друг. Без канцелярита."
)


def build_system_prompt(workspace: Workspace) -> str:
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.timezone))
    parts = [
        BASE_PROMPT,
        f"Сейчас: {now:%Y-%m-%d %H:%M}, {now:%A} ({settings.timezone}).",
    ]
    if workspace.type == WorkspaceType.group:
        parts.append(GROUP_ADDON)
    persona = (workspace.settings or {}).get("persona")
    parts.append(
        f"Инструкции этого чата (заданы его участниками):\n{persona}"
        if persona
        else DEFAULT_PERSONA
    )
    return "\n".join(parts)
