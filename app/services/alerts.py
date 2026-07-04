import logging
import re

from aiogram import Bot
from redis.asyncio import Redis

from app.config import get_settings

logger = logging.getLogger("gennady.alerts")

_redis = Redis.from_url(get_settings().redis_url)

LLM_FAILURE_THRESHOLD = 3
LLM_FAILURE_WINDOW_SECONDS = 600

# Текст исключения может содержать ключи/пароли (URL с кредами, заголовки,
# тела ответов) — вычищаем перед показом в чате или алерте.
_SECRET_PATTERNS = [
    re.compile(r"sk-or-[A-Za-z0-9_-]+"),  # OpenRouter
    re.compile(r"tvly-[A-Za-z0-9_-]+"),  # Tavily
    re.compile(r"\d{8,10}:[A-Za-z0-9_-]{35}"),  # Telegram bot token
    re.compile(r"://[^/\s:@]+:[^/\s@]+@"),  # креды в URL
    re.compile(
        r"(api[_-]?key|token|secret|password|authorization)\s*[=:]\s*\S+",
        re.IGNORECASE,
    ),
]


def safe_error_text(exc: BaseException, limit: int = 200) -> str:
    """«ИмяТипа: сообщение» без секретов, обрезанное до limit.

    Возвращает plain text — для HTML-parse_mode оберни в html.escape()."""
    text = f"{type(exc).__name__}: {exc}"
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text[:limit]


async def notify_admins(
    bot: Bot, text: str, *, kind: str = "generic", cooldown_seconds: int = 1800
) -> None:
    """Шлёт текст всем админам, но не чаще раза в cooldown_seconds на kind —
    защита от спама при флаппинге одной и той же проблемы."""
    if not await _redis.set(f"alert:cooldown:{kind}", "1", ex=cooldown_seconds, nx=True):
        return
    for admin_id in get_settings().admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.exception("Не смог отправить алерт админу %s", admin_id)


async def record_llm_failure(bot: Bot) -> None:
    """Считает подряд идущие сбои LLM; при накоплении порога — алерт и сброс счётчика."""
    key = "alerts:llmfail"
    count = await _redis.incr(key)
    if count == 1:
        await _redis.expire(key, LLM_FAILURE_WINDOW_SECONDS)
    if count >= LLM_FAILURE_THRESHOLD:
        await _redis.delete(key)
        await notify_admins(
            bot,
            f"⚠️ LLM падает подряд ({count} сбоев за {LLM_FAILURE_WINDOW_SECONDS // 60} мин) — глянь логи.",
            kind="llmfail",
        )
