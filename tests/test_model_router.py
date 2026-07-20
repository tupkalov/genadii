"""Роутер моделей: дешёвая ведёт простые ходы, на инструмент/escalate — Sonnet."""
from decimal import Decimal

from app.config import get_settings
from app.llm.client import LlmResult
from app.services import app_settings, llm_chat


def _final(model: str, text: str = "ответ") -> LlmResult:
    return LlmResult(
        content=text, model=model, prompt_tokens=1, completion_tokens=1,
        cost_usd=Decimal("0"), latency_ms=1,
        raw_message={"role": "assistant", "content": text},
    )


def _tool(model: str, name: str = "escalate") -> LlmResult:
    call = {"id": "c1", "type": "function",
            "function": {"name": name, "arguments": "{}"}}
    return LlmResult(
        content="", model=model, prompt_tokens=1, completion_tokens=1,
        cost_usd=Decimal("0"), latency_ms=1, tool_calls=[call],
        raw_message={"role": "assistant", "content": None, "tool_calls": [call]},
    )


async def _base_smart(session):
    await app_settings.reset_default_model(session)  # base = конфиг (не БД)
    base = llm_chat.pick_model(
        __import__("types").SimpleNamespace(settings={}),
        default_model=await app_settings.default_model(session),
    )
    return base, get_settings().smart_model


async def test_simple_turn_stays_cheap(session, workspace, user, monkeypatch):
    base, smart = await _base_smart(session)
    calls: list[str] = []

    async def fake(messages, model, tools=None):
        calls.append(model)
        return _final(model)

    monkeypatch.setattr(llm_chat.client, "chat", fake)
    out = await llm_chat.generate_reply(session, workspace, user, guard_offtopic=False)
    assert calls == [base]  # только дешёвая, эскалации не было
    assert smart not in calls
    assert out.text == "ответ"


async def test_tool_call_escalates_to_smart(session, workspace, user, monkeypatch):
    base, smart = await _base_smart(session)
    calls: list[str] = []

    async def fake(messages, model, tools=None):
        calls.append(model)
        if model == base:
            return _tool(base, "add-tasks")  # дешёвая тянется к инструменту
        return _final(smart)  # умная доводит ход

    monkeypatch.setattr(llm_chat.client, "chat", fake)
    out = await llm_chat.generate_reply(session, workspace, user, guard_offtopic=False)
    assert calls == [base, smart]  # переигран на Sonnet
    assert out.text == "ответ 🧠"  # помечен маркером умной модели


async def test_escalate_schema_only_for_cheap(session, workspace, user, monkeypatch):
    base, smart = await _base_smart(session)
    seen: list[tuple[str, list[str]]] = []

    async def fake(messages, model, tools=None):
        seen.append((model, [t["function"]["name"] for t in (tools or [])]))
        if model == base:
            return _tool(base, "escalate")
        return _final(smart)

    monkeypatch.setattr(llm_chat.client, "chat", fake)
    await llm_chat.generate_reply(session, workspace, user, guard_offtopic=False)
    base_tools = next(names for m, names in seen if m == base)
    smart_tools = next(names for m, names in seen if m == smart)
    assert "escalate" in base_tools       # дешёвой даём способ передать ход
    assert "escalate" not in smart_tools  # умной эскалировать некуда


async def test_per_chat_tiers_used(session, workspace, user, monkeypatch):
    # per-chat workhorse/smart перекрывают глобальные; роутер меж ними работает
    workspace.settings = {"workhorse": "chat/cheap", "smart": "chat/smart"}
    calls: list[str] = []

    async def fake(messages, model, tools=None):
        calls.append(model)
        if model == "chat/cheap":
            return _tool("chat/cheap", "add-tasks")
        return _final("chat/smart")

    monkeypatch.setattr(llm_chat.client, "chat", fake)
    out = await llm_chat.generate_reply(session, workspace, user, guard_offtopic=False)
    assert calls == ["chat/cheap", "chat/smart"]
    assert out.text == "ответ 🧠"


async def test_pinned_model_no_router(session, workspace, user, monkeypatch):
    # чат с явным /model override — роутер не вмешивается, всё на этой модели
    workspace.settings = {"model_override": "some/pinned-model"}
    calls: list[str] = []

    async def fake(messages, model, tools=None):
        calls.append(model)
        return _final(model)

    monkeypatch.setattr(llm_chat.client, "chat", fake)
    out = await llm_chat.generate_reply(session, workspace, user, guard_offtopic=False)
    assert calls == ["some/pinned-model"]
    assert out.text == "ответ"
