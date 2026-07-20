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


async def test_smart_model_failure_falls_back_to_base(
    session, workspace, user, monkeypatch
):
    """Эскалация — оптимизация: падение smart-модели не должно ронять ход."""
    smart = get_settings().smart_model
    # base — как его резолвит generate_reply: глобальный дефолт из БД, иначе
    # конфиг (не завязываемся на конкретную модель — она может быть сменена)
    global_default = await app_settings.default_model(session)
    base = llm_chat.pick_model(workspace, default_model=global_default)
    calls: list[str] = []

    async def fake_chat(messages, model, tools=None):
        calls.append(model)
        if model == smart:
            raise LlmError(f"OpenRouter 400: {model} is not a valid model ID")
        return _result(model)

    monkeypatch.setattr(llm_chat.client, "chat", fake_chat)
    # Эскалация с первого же раунда — не гоняем 3 фиктивных tool-итерации
    monkeypatch.setattr(llm_chat, "ESCALATE_AFTER_ITERATIONS", 0)

    outcome = await llm_chat.generate_reply(session, workspace, user)

    assert calls == [smart, base]  # упала умная → доехали на базовой
    assert outcome.text == "ответ"
    assert [u.model for u in outcome.usages] == [base]


async def test_base_model_failure_still_raises(session, workspace, user, monkeypatch):
    async def fake_chat(messages, model, tools=None):
        raise LlmError("OpenRouter недоступен: boom")

    monkeypatch.setattr(llm_chat.client, "chat", fake_chat)

    with pytest.raises(LlmError):
        await llm_chat.generate_reply(session, workspace, user)
