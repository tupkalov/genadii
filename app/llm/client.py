import base64
import time
from dataclasses import dataclass, field
from decimal import Decimal

import httpx

from app.config import get_settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class LlmError(Exception):
    pass


@dataclass
class LlmResult:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    latency_ms: int
    tool_calls: list[dict] = field(default_factory=list)
    raw_message: dict = field(default_factory=dict)
    images: list[bytes] = field(default_factory=list)  # сгенерированные картинки


async def chat(
    messages: list[dict], model: str, tools: list[dict] | None = None
) -> LlmResult:
    """Один вызов OpenRouter chat completions с учётом стоимости."""
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    body: dict = {
        "model": model,
        "messages": messages,
        # просим OpenRouter вернуть стоимость запроса в ответе
        "usage": {"include": True},
    }
    if tools:
        body["tools"] = tools

    started = time.monotonic()
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "X-Title": "Smart Gennady",
            },
            json=body,
        )
    latency_ms = int((time.monotonic() - started) * 1000)

    if response.status_code != 200:
        raise LlmError(f"OpenRouter {response.status_code}: {response.text[:300]}")

    data = response.json()
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError) as exc:
        raise LlmError(f"Неожиданный ответ OpenRouter: {data}") from exc

    usage = data.get("usage") or {}
    return LlmResult(
        content=message.get("content") or "",
        model=data.get("model", model),
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        cost_usd=Decimal(str(usage.get("cost", 0))),
        latency_ms=latency_ms,
        tool_calls=message.get("tool_calls") or [],
        raw_message=message,
    )


def _decode_data_url(url: str) -> bytes | None:
    if not url.startswith("data:"):
        return None
    try:
        return base64.b64decode(url.split(",", 1)[1])
    except (IndexError, ValueError):
        return None


async def generate_image(prompt: str, model: str) -> LlmResult:
    """Генерация изображения через chat completions с modalities=["image","text"].

    Картинки приходят в message.images как base64 data-URL.
    """
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    started = time.monotonic()
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "X-Title": "Smart Gennady",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "modalities": ["image", "text"],
                "usage": {"include": True},
            },
        )
    latency_ms = int((time.monotonic() - started) * 1000)

    if response.status_code != 200:
        raise LlmError(f"OpenRouter {response.status_code}: {response.text[:300]}")

    data = response.json()
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError) as exc:
        raise LlmError(f"Неожиданный ответ OpenRouter: {data}") from exc

    images = []
    for img in message.get("images") or []:
        decoded = _decode_data_url(img.get("image_url", {}).get("url", ""))
        if decoded:
            images.append(decoded)

    usage = data.get("usage") or {}
    return LlmResult(
        content=message.get("content") or "",
        model=data.get("model", model),
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        cost_usd=Decimal(str(usage.get("cost", 0))),
        latency_ms=latency_ms,
        images=images,
    )
