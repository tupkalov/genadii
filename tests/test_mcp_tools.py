from sqlalchemy import delete

from app.db.models import McpServer
from app.services import mcp

FAKE_TOOLS = [
    {"name": "add_task", "description": "Добавить задачу", "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}}},
    {"name": "list_tasks", "description": "Список задач", "input_schema": {"type": "object", "properties": {}}},
]


async def _add_server(session, workspace, user, name, enabled=True, tools_cache=None):
    server = McpServer(
        workspace_id=workspace.id,
        name=name,
        url=f"http://{name}:8000/mcp",
        enabled=enabled,
        tools_cache=tools_cache,
        created_by_id=user.id,
    )
    session.add(server)
    await session.commit()
    await mcp.invalidate(server.id)
    return server


async def _cleanup(session, workspace):
    await session.execute(
        delete(McpServer).where(McpServer.workspace_id == workspace.id)
    )
    await session.commit()


async def test_tools_are_namespaced(session, workspace, user, monkeypatch):
    await _add_server(session, workspace, user, "todo")

    async def fake_discover(url, token):
        return FAKE_TOOLS

    monkeypatch.setattr(mcp, "_discover", fake_discover)
    tools = await mcp.workspace_mcp_tools(session, workspace)
    names = {t.name for t in tools}
    assert names == {"mcp_todo_add_task", "mcp_todo_list_tasks"}
    assert all(t.description.startswith("[MCP:todo]") for t in tools)
    await _cleanup(session, workspace)


async def test_disabled_server_skipped(session, workspace, user, monkeypatch):
    await _add_server(session, workspace, user, "off1", enabled=False)

    async def fake_discover(url, token):
        return FAKE_TOOLS

    monkeypatch.setattr(mcp, "_discover", fake_discover)
    assert await mcp.workspace_mcp_tools(session, workspace) == []
    await _cleanup(session, workspace)


async def test_broken_server_does_not_break_others(
    session, workspace, user, monkeypatch
):
    await _add_server(session, workspace, user, "good")
    await _add_server(session, workspace, user, "broken")

    async def fake_discover(url, token):
        if "broken" in url:
            raise ConnectionError("connection refused")
        return FAKE_TOOLS

    monkeypatch.setattr(mcp, "_discover", fake_discover)
    tools = await mcp.workspace_mcp_tools(session, workspace)
    # broken отдаёт только фолбэк (его нет) — но good работает
    assert {t.name for t in tools} == {"mcp_good_add_task", "mcp_good_list_tasks"}
    await _cleanup(session, workspace)


async def test_broken_server_falls_back_to_db_cache(
    session, workspace, user, monkeypatch
):
    await _add_server(
        session, workspace, user, "flaky", tools_cache=[FAKE_TOOLS[0]]
    )

    async def fake_discover(url, token):
        raise ConnectionError("down")

    monkeypatch.setattr(mcp, "_discover", fake_discover)
    tools = await mcp.workspace_mcp_tools(session, workspace)
    assert [t.name for t in tools] == ["mcp_flaky_add_task"]
    await _cleanup(session, workspace)


async def test_discover_cached_in_redis(session, workspace, user, monkeypatch):
    server = await _add_server(session, workspace, user, "cachetest")
    calls = {"n": 0}

    async def fake_discover(url, token):
        calls["n"] += 1
        return FAKE_TOOLS

    monkeypatch.setattr(mcp, "_discover", fake_discover)
    await mcp.workspace_mcp_tools(session, workspace)
    await mcp.workspace_mcp_tools(session, workspace)
    assert calls["n"] == 1  # второй раз — из Redis
    await mcp.invalidate(server.id)
    await _cleanup(session, workspace)
