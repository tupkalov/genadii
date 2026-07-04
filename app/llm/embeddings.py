import hashlib
import json
import logging

import httpx
from redis.asyncio import Redis

from app.config import get_settings
from app.llm import http as llm_http
from app.llm.retry import request_with_retry

logger = logging.getLogger("gennady.embeddings")

OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"
CACHE_TTL_SECONDS = 600

_redis = Redis.from_url(get_settings().redis_url)


def available() -> bool:
    return bool(get_settings().openrouter_api_key)


def _cache_key(model: str, text: str) -> str:
    return f"emb:{model}:{hashlib.sha256(text.encode()).hexdigest()}"


async def embed(text: str) -> list[float] | None:
    """Embedding через OpenRouter (тот же ключ, что и для чата).

    Без ключа возвращает None — память работает на текстовом поиске.
    Сетевые ошибки и 5xx ретраятся с backoff; после исчерпания — исключение
    (вызывающий код решает, как деградировать).
    Результат кэшируется в Redis (короткий TTL): экономит повторные вызовы
    при ранжировании памяти и dedup-проверках; Redis недоступен — идём
    напрямую.
    """
    settings = get_settings()
    if not settings.openrouter_api_key:
        return None

    text = text[:8000]
    key = _cache_key(settings.embedding_model, text)
    try:
        cached = await _redis.get(key)
        if cached is not None:
            return json.loads(cached)
    except Exception as exc:
        logger.debug("Redis-кэш эмбеддингов недоступен (чтение): %s", exc)

    async def _do_request() -> httpx.Response:
        return await llm_http.client.post(
            OPENROUTER_EMBEDDINGS_URL,
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "X-Title": "Smart Gennady",
            },
            json={"model": settings.embedding_model, "input": text},
            timeout=30,
        )

    response = await request_with_retry(_do_request)
    vector = response.json()["data"][0]["embedding"]

    try:
        await _redis.set(key, json.dumps(vector), ex=CACHE_TTL_SECONDS)
    except Exception as exc:
        logger.debug("Redis-кэш эмбеддингов недоступен (запись): %s", exc)
    return vector
