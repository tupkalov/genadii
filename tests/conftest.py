import random

import pytest
from sqlalchemy import delete

from app.db.models import (
    McpServer,
    MemoryEntry,
    Message,
    SavedScript,
    ScheduledTask,
    Skill,
    User,
    Webhook,
    Workspace,
    WorkspaceType,
)
from app.db.session import session_factory


def _test_id() -> int:
    # Диапазон заведомо выше реальных Telegram id — риск коллизии пренебрежимо мал.
    return random.randint(10**15, 2 * 10**15)


@pytest.fixture
async def session():
    async with session_factory() as s:
        yield s
        await s.rollback()


@pytest.fixture
async def workspace(session):
    ws = Workspace(type=WorkspaceType.personal, tg_chat_id=-_test_id(), settings={})
    session.add(ws)
    await session.commit()
    yield ws
    await session.execute(delete(MemoryEntry).where(MemoryEntry.workspace_id == ws.id))
    await session.execute(delete(SavedScript).where(SavedScript.workspace_id == ws.id))
    await session.execute(delete(Workspace).where(Workspace.id == ws.id))
    await session.commit()


@pytest.fixture
async def other_workspace(session):
    ws = Workspace(type=WorkspaceType.personal, tg_chat_id=-_test_id(), settings={})
    session.add(ws)
    await session.commit()
    yield ws
    await session.execute(delete(MemoryEntry).where(MemoryEntry.workspace_id == ws.id))
    await session.execute(delete(SavedScript).where(SavedScript.workspace_id == ws.id))
    await session.execute(delete(Workspace).where(Workspace.id == ws.id))
    await session.commit()


@pytest.fixture
async def user(session):
    u = User(tg_id=_test_id(), username="testuser", first_name="Test")
    session.add(u)
    await session.commit()
    yield u
    # Порядок финализации fixture'ов не гарантирован (user не зависит от
    # workspace) — чистим ссылающиеся строки здесь тоже, чтобы не словить
    # FK-violation независимо от того, что финализируется раньше.
    await session.execute(delete(Message).where(Message.user_id == u.id))
    await session.execute(delete(ScheduledTask).where(ScheduledTask.user_id == u.id))
    await session.execute(delete(SavedScript).where(SavedScript.created_by_id == u.id))
    await session.execute(delete(MemoryEntry).where(MemoryEntry.created_by_id == u.id))
    await session.execute(delete(Webhook).where(Webhook.created_by_id == u.id))
    await session.execute(delete(McpServer).where(McpServer.created_by_id == u.id))
    await session.execute(delete(Skill).where(Skill.created_by_id == u.id))
    await session.execute(delete(User).where(User.id == u.id))
    await session.commit()
