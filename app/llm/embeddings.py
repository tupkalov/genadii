import asyncio

import httpx

from app.config import get_settings

OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"

RETRIES = 3
BACKOFF_SECONDS = (0.5, 2.0)


def available() -> bool:
    return bool(get_settings().openrouter_api_key)


async def embed(text: str) -> list[float] | None:
    """Embedding через OpenRouter (тот же ключ, что и для чата).

    Без ключа возвращает None — память работает на текстовом поиске.
    Сетевые ошибки и 5xx ретраятся с backoff; после исчерпания — исключение
    (вызывающий код решает, как деградировать).
    """
    settings = get_settings()
    if not settings.openrouter_api_key:
        return None

    last_error: Exception | None = None
    for attempt in range(RETRIES):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    OPENROUTER_EMBEDDINGS_URL,
                    headers={
                        "Authorization": f"Bearer {settings.openrouter_api_key}",
                        "X-Title": "Smart Gennady",
                    },
                    json={"model": settings.embedding_model, "input": text[:8000]},
                )
            response.raise_for_status()
            return response.json()["data"][0]["embedding"]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                raise  # 4xx — ретраить бессмысленно
            last_error = exc
        except httpx.HTTPError as exc:
            last_error = exc
        if attempt < RETRIES - 1:
            await asyncio.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
    raise last_error
