"""OAuth-авторизация MCP-серверов.

Протокол (discovery, динамическая регистрация клиента, PKCE, refresh) делает
SDK через OAuthClientProvider; наша часть — хранилище токенов в строке
mcp_servers и связка «ссылка в Telegram → callback в браузере». Интерактивный
флоу живёт в процессе app (бот и FastAPI крутятся в одном event loop):
redirect_handler шлёт ссылку в чат, callback-роут резолвит Future по state.
Воркер и обычные вызовы используют неинтерактивный провайдер — только
сохранённые токены с авто-refresh.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from sqlalchemy import select, update

from app.config import get_settings
from app.db.models import McpServer
from app.db.session import session_factory

logger = logging.getLogger("gennady.mcp_auth")

AUTH_FLOW_TIMEOUT = 300  # сколько ждём, пока пользователь нажмёт «Разрешить»


def callback_url() -> str:
    base = get_settings().webhook_base_url.rstrip("/")
    return f"{base}/oauth/callback"


def base_url_configured() -> bool:
    return bool(get_settings().webhook_base_url.strip())


class DbTokenStorage(TokenStorage):
    """Токены и client_info живут в строке mcp_servers (короткие транзакции —
    хранилище дёргается и из бота, и из воркера)."""

    def __init__(self, server_id: int):
        self.server_id = server_id

    async def get_tokens(self) -> OAuthToken | None:
        async with session_factory() as session:
            data = await session.scalar(
                select(McpServer.oauth_tokens).where(McpServer.id == self.server_id)
            )
        return OAuthToken.model_validate(data) if data else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        async with session_factory() as session:
            await session.execute(
                update(McpServer)
                .where(McpServer.id == self.server_id)
                .values(oauth_tokens=tokens.model_dump(mode="json"))
            )
            await session.commit()

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        async with session_factory() as session:
            data = await session.scalar(
                select(McpServer.oauth_client_info).where(
                    McpServer.id == self.server_id
                )
            )
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def set_client_info(self, info: OAuthClientInformationFull) -> None:
        async with session_factory() as session:
            await session.execute(
                update(McpServer)
                .where(McpServer.id == self.server_id)
                .values(oauth_client_info=info.model_dump(mode="json"))
            )
            await session.commit()


def _client_metadata() -> OAuthClientMetadata:
    return OAuthClientMetadata(
        client_name="Smart Gennady",
        redirect_uris=[callback_url()],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
    )


# --- Интерактивный флоу: ссылка в чат, ожидание callback'а --------------------


@dataclass
class _PendingAuth:
    future: asyncio.Future = field(
        default_factory=lambda: asyncio.get_event_loop().create_future()
    )


_pending: dict[str, _PendingAuth] = {}  # state -> ожидание callback'а


def resolve_callback(state: str, code: str) -> bool:
    """Из FastAPI-роута: отдаёт code ожидающему флоу. False — state неизвестен."""
    pending = _pending.get(state)
    if pending is None or pending.future.done():
        return False
    pending.future.set_result(code)
    return True


def interactive_provider(server: McpServer, on_auth_url) -> OAuthClientProvider:
    """Провайдер для /mcp add|auth: ссылку шлём в чат, code ждём из callback'а.

    on_auth_url: async (url: str) -> None — доставка ссылки пользователю.
    """

    flow_state: dict[str, str] = {}  # state этого конкретного флоу

    async def redirect_handler(auth_url: str) -> None:
        state = parse_qs(urlparse(auth_url).query).get("state", [""])[0]
        if state:
            flow_state["state"] = state
            _pending[state] = _PendingAuth()
        await on_auth_url(auth_url)

    async def callback_handler() -> tuple[str, str | None]:
        state = flow_state.get("state", "")
        pending = _pending.get(state)
        if pending is None:
            raise RuntimeError("OAuth-флоу не инициализирован (нет state)")
        try:
            async with asyncio.timeout(AUTH_FLOW_TIMEOUT):
                code = await pending.future
        finally:
            _pending.pop(state, None)
        return code, state

    return OAuthClientProvider(
        server_url=server.url,
        client_metadata=_client_metadata(),
        storage=DbTokenStorage(server.id),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


def stored_provider(server_id: int, server_url: str) -> OAuthClientProvider:
    """Неинтерактивный провайдер (обычные вызовы, воркер): только сохранённые
    токены + авто-refresh; если сервер требует новую авторизацию — ошибка с
    подсказкой перезапустить /mcp auth."""

    async def redirect_handler(auth_url: str) -> None:
        raise RuntimeError(
            "MCP-сервер требует повторной авторизации — попроси админа "
            "выполнить /mcp auth"
        )

    async def callback_handler() -> tuple[str, str | None]:
        raise RuntimeError("OAuth-callback недоступен вне /mcp auth")

    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=_client_metadata(),
        storage=DbTokenStorage(server_id),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


def has_oauth(server: McpServer) -> bool:
    return bool(server.oauth_tokens)
