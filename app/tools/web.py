import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings
from app.tools.registry import Tool, ToolContext, register

TAVILY_URL = "https://api.tavily.com/search"
FETCH_TEXT_LIMIT = 6000
FETCH_BYTES_LIMIT = 2_000_000


def _is_private_host(hostname: str) -> bool:
    """Грубая защита от SSRF: не ходим на localhost и приватные сети."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return True
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    return False


async def _web_search(ctx: ToolContext, query: str) -> str:
    settings = get_settings()
    if not settings.tavily_api_key:
        return "Ошибка: TAVILY_API_KEY не задан — поиск недоступен."

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TAVILY_URL,
            headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
            json={"query": query, "max_results": 5, "include_answer": True},
        )
    if response.status_code != 200:
        return f"Ошибка поиска: Tavily {response.status_code}: {response.text[:200]}"

    data = response.json()
    parts = []
    if data.get("answer"):
        parts.append(f"Краткий ответ: {data['answer']}")
    for r in data.get("results", []):
        parts.append(f"- {r.get('title')}\n  {r.get('url')}\n  {r.get('content', '')[:300]}")
    return "\n".join(parts) or "Поиск ничего не нашёл."


async def _fetch_url(ctx: ToolContext, url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "Ошибка: поддерживаются только http/https ссылки."
    if not parsed.hostname or _is_private_host(parsed.hostname):
        return "Ошибка: этот адрес недоступен."

    try:
        async with httpx.AsyncClient(
            timeout=25, follow_redirects=True, max_redirects=5
        ) as client:
            response = await client.get(
                url, headers={"User-Agent": "SmartGennady/1.0 (+telegram bot)"}
            )
    except httpx.HTTPError as exc:
        return f"Ошибка загрузки: {exc}"

    if response.status_code != 200:
        return f"Ошибка: HTTP {response.status_code}"

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        return f"Ошибка: не текстовая страница ({content_type})."

    soup = BeautifulSoup(response.content[:FETCH_BYTES_LIMIT], "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else url
    text = " ".join(soup.get_text(separator=" ").split())

    if not text:
        return "Страница загрузилась, но текста на ней нет."
    return f"[{title}]\n{text[:FETCH_TEXT_LIMIT]}"


register(
    Tool(
        name="web_search",
        description=(
            "Поиск в интернете. Используй для актуальных фактов, новостей, цен — "
            "всего, чего нет в твоих знаниях или что могло устареть."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос"}
            },
            "required": ["query"],
        },
        handler=_web_search,
        default_enabled=True,
    )
)

register(
    Tool(
        name="fetch_url",
        description=(
            "Загрузить страницу по URL и получить её текст. Используй, когда "
            "пользователь кидает ссылку или когда нужны детали после web_search."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Полный URL страницы"}
            },
            "required": ["url"],
        },
        handler=_fetch_url,
        default_enabled=True,
    )
)
