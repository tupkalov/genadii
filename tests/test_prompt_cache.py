"""cache_control-брейкпоинты для Anthropic-моделей через OpenRouter."""
from app.config import get_settings
from app.llm.client import with_cache_control

SONNET = "anthropic/claude-sonnet-5"
DEEPSEEK = "deepseek/deepseek-v4-flash"


def _msgs():
    return [
        {"role": "system", "content": "большой системный промпт"},
        {"role": "user", "content": "первое"},
        {"role": "assistant", "content": "ответ"},
        {"role": "user", "content": "последнее сообщение"},
    ]


def test_non_anthropic_unchanged():
    msgs = _msgs()
    assert with_cache_control(msgs, DEEPSEEK) == msgs


def test_anthropic_marks_system_and_last():
    out = with_cache_control(_msgs(), SONNET)
    # системный промпт → блок с cache_control
    assert out[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert out[0]["content"][0]["text"] == "большой системный промпт"
    # последнее сообщение → тоже
    assert out[-1]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert out[-1]["content"][0]["text"] == "последнее сообщение"
    # промежуточные не трогаем
    assert out[1] == {"role": "user", "content": "первое"}


def test_does_not_mutate_input():
    msgs = _msgs()
    with_cache_control(msgs, SONNET)
    assert isinstance(msgs[0]["content"], str)  # оригинал не изменён
    assert isinstance(msgs[-1]["content"], str)


def test_last_tool_message_marked():
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "tool_call_id": "x", "content": "результат инструмента"},
    ]
    out = with_cache_control(msgs, SONNET)
    assert out[-1]["content"][0]["text"] == "результат инструмента"
    assert out[-1]["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_multimodal_last_not_broken():
    # мультимодальный последний контент (список) — не трогаем, не падаем
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": [{"type": "image_url", "image_url": {}}]},
    ]
    out = with_cache_control(msgs, SONNET)
    assert out[-1]["content"] == [{"type": "image_url", "image_url": {}}]


def test_disabled_by_flag(monkeypatch):
    monkeypatch.setattr(get_settings(), "prompt_cache", False)
    msgs = _msgs()
    assert with_cache_control(msgs, SONNET) == msgs
