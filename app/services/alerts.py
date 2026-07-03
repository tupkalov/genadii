import logging

from aiogram import Bot
from redis.asyncio import Redis

from app.config import get_settings

logger = logging.getLogger("gennady.alerts")

_redis = Redis.from_url(get_settings().redis_url)

LLM_FAILURE_THRESHOLD = 3
LLM_FAILURE_WINDOW_SECONDS = 600


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
