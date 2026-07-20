from decimal import Decimal

import pytest

from app.config import get_settings
from app.llm.client import LlmError, LlmResult
from app.services import app_settings, llm_chat


def _result(model: str) -> LlmResult:
    return LlmResult(
        content="ответ",
        model=model,
        prompt_tokens=1,
        completion_tokens=1,
        cost_usd=Decimal("0"),
        latency_ms=1,
        raw_message={"role": "assistant", "content": "ответ"},
    )


def _tool(model: str) -> LlmResult:
    call = {"id": "c1", "type": "function",
            "function": {"name": "escalate", "arguments": "{}"}}
    return LlmResult(
        content="", model=model, prompt_tokens=1, completion_tokens=1,
        cost_usd=Decimal("0"), latency_ms=1, tool_calls=[call],
        raw_message={"role": "assistant", "content": None, "tool_calls": [call]},
    )


async def test_smart_model_failure_falls_back_to_base(
    session, workspace, user, monkeypatch
):
    """Эскалация — оптимизация: падение smart-модели не должно ронять ход."""
    await app_settings.reset_default_model(session)
    smart = get_settings().smart_model
    base = llm_chat.pick_model(
        workspace, default_model=await app_settings.default_model(session)
    )
    calls: list[str] = []

    async def fake_chat(messages, model, tools=None):
        calls.append(model)
        if model == base and calls.count(base) == 1:
            return _tool(base)  # первый ход дешёвой → сигнал эскалации
        if model == smart:
            raise LlmError(f"OpenRouter 400: {model} is not a valid model ID")
        return _result(model)  # фолбэк на дешёвую → финальный текст

    monkeypatch.setattr(llm_chat.client, "chat", fake_chat)

    outcome = await llm_chat.generate_reply(session, workspace, user, guard_offtopic=False)

    assert calls == [base, smart, base]  # дешёвая → эскалация → smart упал → дешёвая
    assert outcome.text == "ответ"


async def test_base_model_failure_still_raises(session, workspace, user, monkeypatch):
    async def fake_chat(messages, model, tools=None):
        raise LlmError("OpenRouter недоступен: boom")

    monkeypatch.setattr(llm_chat.client, "chat", fake_chat)

    with pytest.raises(LlmError):
        await llm_chat.generate_reply(session, workspace, user)
