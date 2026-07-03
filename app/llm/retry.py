import asyncio
from collections.abc import Awaitable, Callable

import httpx

RETRIES = 3
BACKOFF_SECONDS = (0.5, 2.0)


async def request_with_retry(
    request_fn: Callable[[], Awaitable[httpx.Response]],
) -> httpx.Response:
    """Повторяет httpx-запрос при 5xx/сетевых ошибках с backoff; 4xx — сразу наружу."""
    last_error: Exception | None = None
    for attempt in range(RETRIES):
        try:
            response = await request_fn()
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                raise
            last_error = exc
        except httpx.HTTPError as exc:
            last_error = exc
        if attempt < RETRIES - 1:
            await asyncio.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
    raise last_error
