import asyncio
import base64
import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from decimal import Decimal

import httpx

from app.config import get_settings
from app.llm import http as llm_http
from app.llm.retry import BACKOFF_SECONDS, RETRIES, request_with_retry

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

    async def _do_request() -> httpx.Response:
        return await llm_http.client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "X-Title": "Smart Gennady",
            },
            json=body,
            timeout=90,
        )

    try:
        response = await request_with_retry(_do_request)
    except httpx.HTTPStatusError as exc:
        raise LlmError(
            f"OpenRouter {exc.response.status_code}: {exc.response.text[:300]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise LlmError(f"OpenRouter недоступен: {exc}") from exc
    latency_ms = int((time.monotonic() - started) * 1000)

    try:
        data = response.json()
    except ValueError as exc:  # не-JSON: HTML-страница ошибки шлюза, пустой ответ
        raise LlmError(
            f"OpenRouter вернул не-JSON ({response.status_code}): {response.text[:300]}"
        ) from exc
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


def _merge_tool_call_deltas(acc: dict[int, dict], deltas: list[dict]) -> None:
    """Собирает tool_calls из потоковых фрагментов (приходят по index)."""
    for d in deltas:
        idx = d.get("index", 0)
        slot = acc.setdefault(
            idx, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
        )
        if d.get("id"):
            slot["id"] = d["id"]
        fn = d.get("function") or {}
        if fn.get("name"):
            slot["function"]["name"] = fn["name"]
        if fn.get("arguments"):
            slot["function"]["arguments"] += fn["arguments"]


async def chat_stream(
    messages: list[dict],
    model: str,
    tools: list[dict] | None,
    on_delta: Callable[[str], None] | None = None,
) -> LlmResult:
    """Потоковый вызов: on_delta зовётся на каждый кусок текста; финал — LlmResult
    (с накопленными content/tool_calls/usage)."""
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    body: dict = {
        "model": model,
        "messages": messages,
        "stream": True,
        "usage": {"include": True},
    }
    if tools:
        body["tools"] = tools

    started = time.monotonic()
    last_error: Exception | None = None

    # Ретраим только если сбой случился ДО первого куска в on_delta — иначе
    # повтор задублирует/испортит уже частично отправленное сообщение.
    for attempt in range(RETRIES):
        content_parts: list[str] = []
        tool_acc: dict[int, dict] = {}
        usage: dict = {}
        resolved_model = model

        try:
            async with llm_http.client.stream(
                "POST",
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "X-Title": "Smart Gennady",
                },
                json=body,
                timeout=180,
            ) as response:
                if response.status_code != 200:
                    text = (await response.aread()).decode(errors="replace")
                    raise LlmError(f"OpenRouter {response.status_code}: {text[:300]}")

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    if chunk.get("model"):
                        resolved_model = chunk["model"]

                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    if delta.get("content"):
                        content_parts.append(delta["content"])
                        if on_delta:
                            on_delta("".join(content_parts))
                    if delta.get("tool_calls"):
                        _merge_tool_call_deltas(tool_acc, delta["tool_calls"])
            break
        except (LlmError, httpx.HTTPError) as exc:
            last_error = exc
            if content_parts or attempt == RETRIES - 1:
                if isinstance(exc, LlmError):
                    raise
                raise LlmError(f"OpenRouter недоступен: {exc}") from exc
            await asyncio.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])

    latency_ms = int((time.monotonic() - started) * 1000)
    tool_calls = [tool_acc[i] for i in sorted(tool_acc)]
    content = "".join(content_parts)
    raw_message: dict = {"role": "assistant", "content": content or None}
    if tool_calls:
        raw_message["tool_calls"] = tool_calls

    return LlmResult(
        content=content,
        model=resolved_model,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        cost_usd=Decimal(str(usage.get("cost", 0))),
        latency_ms=latency_ms,
        tool_calls=tool_calls,
        raw_message=raw_message,
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

    async def _do_request() -> httpx.Response:
        return await llm_http.client.post(
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
            timeout=120,
        )

    try:
        response = await request_with_retry(_do_request)
    except httpx.HTTPStatusError as exc:
        raise LlmError(
            f"OpenRouter {exc.response.status_code}: {exc.response.text[:300]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise LlmError(f"OpenRouter недоступен: {exc}") from exc
    latency_ms = int((time.monotonic() - started) * 1000)

    try:
        data = response.json()
    except ValueError as exc:  # не-JSON: HTML-страница ошибки шлюза, пустой ответ
        raise LlmError(
            f"OpenRouter вернул не-JSON ({response.status_code}): {response.text[:300]}"
        ) from exc
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
