import logging

from aiogram.types import ErrorEvent

logger = logging.getLogger("gennady.errors")


async def on_error(event: ErrorEvent) -> bool:
    """Любая необработанная ошибка — в лог и, по возможности, в чат."""
    exc = event.exception
    logger.exception("Unhandled error: %s", exc, exc_info=exc)

    message = getattr(event.update, "message", None)
    if message is not None:
        try:
            await message.answer(
                "⚠️ Что-то сломалось: "
                f"<code>{type(exc).__name__}: {str(exc)[:200]}</code>\n"
                "Попробуй ещё раз — а это уже в логах."
            )
        except Exception:
            logger.exception("Не смог отправить сообщение об ошибке в чат")
    return True
