from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message
from redis.asyncio import Redis

from app.config import get_settings

WARN_EVERY = 60  # не спамим предупреждением чаще раза в минуту на пользователя


class ThrottleMiddleware(BaseMiddleware):
    """Мягкий rate-limit на пользователя (скользящее окно в Redis)."""

    def __init__(self) -> None:
        self._redis = Redis.from_url(get_settings().redis_url)

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        settings = get_settings()
        if tg_user is None or settings.rate_limit_per_minute <= 0:
            return await handler(event, data)

        key = f"rl:{tg_user.id}"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, 60)

        if count > settings.rate_limit_per_minute:
            warn_key = f"rlwarn:{tg_user.id}"
            if await self._redis.set(warn_key, "1", ex=WARN_EVERY, nx=True):
                try:
                    await event.answer("🐢 Слишком часто — притормози на минутку.")
                except Exception:
                    pass
            return None

        return await handler(event, data)
