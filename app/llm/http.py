"""Общий httpx-клиент для исходящих API-вызовов (OpenRouter, Tavily).

Один клиент = переиспользование TCP/TLS-соединений вместо handshake'а на
каждый вызов. Таймауты задаются per-request. Для fetch_url НЕ используется —
тот ходит на произвольные хосты и разбирает редиректы вручную.
"""

import httpx

client = httpx.AsyncClient(
    timeout=httpx.Timeout(30, connect=10),
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
)


async def aclose() -> None:
    await client.aclose()
