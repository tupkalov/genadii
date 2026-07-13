"""Авто-refresh OAuth-токена MCP: срок и метаданные переживают пересоздание
провайдера, иначе SDK не зовёт refresh и требует ручной /mcp auth каждый час."""
import time

import pytest
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthMetadata,
    OAuthToken,
)
from sqlalchemy import delete

from app.db.models import McpServer
from app.services import mcp_auth
from app.services.mcp_auth import DbTokenStorage, _StoredProvider


async def _server(session, workspace, user):
    srv = McpServer(
        workspace_id=workspace.id,
        name="refresh-test",
        url="https://example.test/mcp",
        created_by_id=user.id,
    )
    session.add(srv)
    await session.commit()
    return srv


async def _cleanup(session, workspace):
    await session.execute(delete(McpServer).where(McpServer.workspace_id == workspace.id))
    await session.commit()


async def test_set_tokens_records_expiry(session, workspace, user):
    srv = await _server(session, workspace, user)
    st = DbTokenStorage(srv.id)
    before = time.time()
    await st.set_tokens(
        OAuthToken(access_token="at", token_type="Bearer", refresh_token="rt", expires_in=3600)
    )
    expiry = await st.get_expiry()
    assert expiry is not None
    # expires_at ≈ now + 3600 (с запасом на исполнение)
    assert before + 3500 <= expiry <= before + 3700
    await _cleanup(session, workspace)


async def test_auth_metadata_roundtrip(session, workspace, user):
    srv = await _server(session, workspace, user)
    st = DbTokenStorage(srv.id)
    meta = OAuthMetadata.model_validate(
        {
            "issuer": "https://auth.example.test",
            "authorization_endpoint": "https://auth.example.test/authorize",
            "token_endpoint": "https://auth.example.test/oauth/access_token",
            "response_types_supported": ["code"],
        }
    )
    await st.set_auth_metadata(meta)
    loaded = await st.get_auth_metadata()
    assert str(loaded.token_endpoint) == "https://auth.example.test/oauth/access_token"
    # expires_at, записанный позже, не затирает метаданные и наоборот
    await st.set_tokens(
        OAuthToken(access_token="at", token_type="Bearer", refresh_token="rt", expires_in=60)
    )
    assert (await st.get_auth_metadata()) is not None
    assert (await st.get_expiry()) is not None
    await _cleanup(session, workspace)


async def test_stored_provider_restores_expiry_and_metadata(session, workspace, user):
    """Главный тест: после _initialize провайдер знает РЕАЛЬНЫЙ срок токена
    (в прошлом → is_token_valid False → SDK пойдёт в refresh), а не None."""
    srv = await _server(session, workspace, user)
    st = DbTokenStorage(srv.id)
    await st.set_client_info(
        OAuthClientInformationFull(
            client_id="cid", redirect_uris=["https://example.test/oauth/callback"]
        )
    )
    await st.set_auth_metadata(
        OAuthMetadata.model_validate(
            {
                "issuer": "https://auth.example.test",
                "authorization_endpoint": "https://auth.example.test/authorize",
                "token_endpoint": "https://auth.example.test/token",
                "response_types_supported": ["code"],
            }
        )
    )
    # токен, истёкший 100 сек назад
    await st.set_tokens(
        OAuthToken(access_token="at", token_type="Bearer", refresh_token="rt", expires_in=-100)
    )

    provider = mcp_auth.stored_provider(srv.id, srv.url)
    assert isinstance(provider, _StoredProvider)
    await provider._initialize()

    assert provider.context.oauth_metadata is not None
    assert provider.context.token_expiry_time is not None
    # срок в прошлом → токен невалиден → есть чем рефрешить → SDK сделает refresh
    assert provider.context.is_token_valid() is False
    assert provider.context.can_refresh_token() is True
    await _cleanup(session, workspace)
