import asyncio

import httpx
import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import delete

from app.db.models import McpServer
from app.main import app
from app.services import mcp_auth
from app.services.mcp_auth import DbTokenStorage


async def _add_server(session, workspace, user):
    server = McpServer(
        workspace_id=workspace.id,
        name="oauth-test",
        url="http://oauth-test:8000/mcp",
        created_by_id=user.id,
    )
    session.add(server)
    await session.commit()
    return server


async def _cleanup(session, workspace):
    await session.execute(
        delete(McpServer).where(McpServer.workspace_id == workspace.id)
    )
    await session.commit()


async def test_token_storage_roundtrip(session, workspace, user):
    server = await _add_server(session, workspace, user)
    storage = DbTokenStorage(server.id)

    assert await storage.get_tokens() is None
    token = OAuthToken(access_token="at-123", token_type="Bearer", refresh_token="rt-456")
    await storage.set_tokens(token)

    loaded = await storage.get_tokens()
    assert loaded.access_token == "at-123"
    assert loaded.refresh_token == "rt-456"

    info = OAuthClientInformationFull(
        client_id="cid-1", redirect_uris=["https://example.com/oauth/callback"]
    )
    await storage.set_client_info(info)
    assert (await storage.get_client_info()).client_id == "cid-1"

    await session.refresh(server)
    assert mcp_auth.has_oauth(server) is True
    await _cleanup(session, workspace)


async def test_resolve_callback_unknown_state():
    assert mcp_auth.resolve_callback("no-such-state", "code") is False


async def test_resolve_callback_delivers_code():
    pending = mcp_auth._PendingAuth()
    mcp_auth._pending["state-abc"] = pending

    assert mcp_auth.resolve_callback("state-abc", "the-code") is True
    assert await asyncio.wait_for(pending.future, timeout=1) == "the-code"
    # Повторный резолв того же state — False (future уже done)
    assert mcp_auth.resolve_callback("state-abc", "another") is False
    mcp_auth._pending.pop("state-abc", None)


@pytest.fixture
def client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_callback_route_resolves_pending(client):
    pending = mcp_auth._PendingAuth()
    mcp_auth._pending["route-state"] = pending
    async with client:
        resp = await client.get(
            "/oauth/callback", params={"state": "route-state", "code": "c-1"}
        )
    assert resp.status_code == 200
    assert "Готово" in resp.text
    assert await asyncio.wait_for(pending.future, timeout=1) == "c-1"
    mcp_auth._pending.pop("route-state", None)


async def test_callback_route_unknown_state_400(client):
    async with client:
        resp = await client.get(
            "/oauth/callback", params={"state": "stale", "code": "c"}
        )
    assert resp.status_code == 400


async def test_callback_route_provider_error(client):
    async with client:
        resp = await client.get(
            "/oauth/callback",
            params={"error": "access_denied", "error_description": "юзер отказал"},
        )
    assert resp.status_code == 400
    assert "юзер отказал" in resp.text


def test_looks_like_auth_required():
    from app.services import mcp

    assert mcp.looks_like_auth_required(Exception("HTTP 401 Unauthorized"))
    assert mcp.looks_like_auth_required(Exception("Client error '401'"))
    assert not mcp.looks_like_auth_required(Exception("connection refused"))


def test_401_detected_inside_exception_group():
    # Живой кейс hubhead.app: anyio заворачивает HTTPStatusError в TaskGroup,
    # str обёртки — «unhandled errors in a TaskGroup», без «401»
    from app.services import mcp

    inner = Exception("Client error '401 Unauthorized' for url 'https://x/mcp'")
    group = BaseExceptionGroup(
        "unhandled errors in a TaskGroup", [ExceptionGroup("sub", [inner])]
    )
    assert mcp.looks_like_auth_required(group)
    assert "401" in mcp.error_text(group)
    assert "TaskGroup" not in mcp.error_text(group)


def test_error_text_plain_exception():
    from app.services import mcp

    assert mcp.error_text(ValueError("boom")) == "ValueError: boom"
