import secrets
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import delete, select

from app.db.models import Message, ScheduledTask, Webhook
from app.main import app


class FakeBot:
    def __init__(self):
        self.sent = []
        self._mid = 1000

    async def send_message(self, chat_id, text, parse_mode=None):
        self._mid += 1
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=self._mid)


@pytest.fixture
def client():
    # ASGITransport не запускает lifespan — бота подкладываем сами
    app.state.bot = FakeBot()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _add_hook(session, workspace, user, mode="notify", **kwargs):
    hook = Webhook(
        workspace_id=workspace.id,
        name=kwargs.get("name", "test-hook"),
        token=secrets.token_urlsafe(24),
        mode=mode,
        instruction=kwargs.get("instruction"),
        enabled=kwargs.get("enabled", True),
        created_by_id=user.id,
    )
    session.add(hook)
    await session.commit()
    return hook


async def _cleanup(session, workspace):
    await session.execute(delete(Webhook).where(Webhook.workspace_id == workspace.id))
    await session.execute(
        delete(ScheduledTask).where(ScheduledTask.workspace_id == workspace.id)
    )
    await session.commit()


async def test_notify_mode_sends_and_saves(session, workspace, user, client):
    hook = await _add_hook(session, workspace, user, mode="notify")
    async with client:
        resp = await client.post(f"/hooks/{hook.token}", json={"status": "deployed"})
    assert resp.status_code == 200

    assert len(app.state.bot.sent) == 1
    chat_id, text = app.state.bot.sent[0]
    assert chat_id == workspace.tg_chat_id
    assert "deployed" in text

    saved = await session.scalar(
        select(Message).where(
            Message.workspace_id == workspace.id,
            Message.content.ilike("%deployed%"),
        )
    )
    assert saved is not None
    await session.refresh(hook)
    assert hook.fire_count == 1
    await _cleanup(session, workspace)


async def test_agent_mode_creates_scheduled_task(session, workspace, user, client):
    hook = await _add_hook(
        session, workspace, user, mode="agent", instruction="Сообщи статус деплоя"
    )
    async with client:
        resp = await client.post(f"/hooks/{hook.token}", json={"build": 42})
    assert resp.status_code == 200

    task = await session.scalar(
        select(ScheduledTask).where(
            ScheduledTask.workspace_id == workspace.id,
            ScheduledTask.kind == "agent_task",
            ScheduledTask.status == "pending",
        )
    )
    assert task is not None
    assert task.user_id == user.id
    assert "Сообщи статус деплоя" in task.payload["text"]
    assert '"build": 42' in task.payload["text"]
    await _cleanup(session, workspace)


async def test_skill_bound_hook_creates_skill_task(session, workspace, user, client):
    from app.db.models import Skill

    skill = Skill(
        workspace_id=workspace.id,
        name="deploy-skill",
        instruction="Проверь статус и сообщи",
        allowed_tools=["web_search"],
        created_by_id=user.id,
    )
    session.add(skill)
    await session.flush()
    hook = await _add_hook(session, workspace, user, mode="agent", name="skillhook")
    hook.skill_id = skill.id
    await session.commit()

    async with client:
        resp = await client.post(f"/hooks/{hook.token}", json={"build": 7})
    assert resp.status_code == 200

    task = await session.scalar(
        select(ScheduledTask).where(
            ScheduledTask.workspace_id == workspace.id,
            ScheduledTask.status == "pending",
        )
    )
    assert task.payload["skill_id"] == skill.id
    assert '"build": 7' in task.payload["event"]

    await _cleanup(session, workspace)
    await session.execute(delete(Skill).where(Skill.id == skill.id))
    await session.commit()


async def test_unknown_token_404(client):
    async with client:
        resp = await client.post("/hooks/definitely-not-a-token", json={})
    assert resp.status_code == 404


async def test_disabled_hook_404(session, workspace, user, client):
    hook = await _add_hook(session, workspace, user, enabled=False)
    async with client:
        resp = await client.post(f"/hooks/{hook.token}", json={})
    assert resp.status_code == 404
    await _cleanup(session, workspace)


async def test_oversized_body_413(session, workspace, user, client):
    hook = await _add_hook(session, workspace, user)
    async with client:
        resp = await client.post(
            f"/hooks/{hook.token}", content=b"x" * 70000
        )
    assert resp.status_code == 413
    await _cleanup(session, workspace)


async def test_rate_limit_429(session, workspace, user, client, monkeypatch):
    from app.api.routes import hooks as hooks_route

    monkeypatch.setattr(hooks_route, "RATE_LIMIT_PER_HOUR", 2)
    hook = await _add_hook(session, workspace, user)
    async with client:
        codes = [
            (await client.post(f"/hooks/{hook.token}", json={})).status_code
            for _ in range(4)
        ]
    assert codes[:2] == [200, 200]
    assert 429 in codes[2:]
    await _cleanup(session, workspace)


async def test_raw_text_body_accepted(session, workspace, user, client):
    hook = await _add_hook(session, workspace, user)
    async with client:
        resp = await client.post(
            f"/hooks/{hook.token}", content=b"plain text alert"
        )
    assert resp.status_code == 200
    assert "plain text alert" in app.state.bot.sent[-1][1]
    await _cleanup(session, workspace)
