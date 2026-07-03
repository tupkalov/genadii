import httpx

from app.config import get_settings
from app.llm.retry import request_with_retry

OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"


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

    async def _do_request() -> httpx.Response:
        async with httpx.AsyncClient(timeout=30) as client:
            return await client.post(
                OPENROUTER_EMBEDDINGS_URL,
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "X-Title": "Smart Gennady",
                },
                json={"model": settings.embedding_model, "input": text[:8000]},
            )

    response = await request_with_retry(_do_request)
    return response.json()["data"][0]["embedding"]
