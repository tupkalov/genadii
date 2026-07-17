"""Guard от ответов «не в тему»: детект, fail-open, извлечение реплики."""
from dataclasses import dataclass

import pytest

from app.services import guard


@dataclass
class _FakeResult:
    content: str
    model: str = "m"
    prompt_tokens: int = 1
    completion_tokens: int = 1


def test_last_user_text_picks_latest_plain():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "первое"},
        {"role": "assistant", "content": "ответ"},
        {"role": "user", "content": "а для диеты че лучше"},
    ]
    assert guard.last_user_text(messages) == "а для диеты че лучше"


def test_last_user_text_skips_systemic_and_multimodal():
    messages = [
        {"role": "user", "content": "нормальный вопрос"},
        {"role": "user", "content": [{"type": "image_url", "image_url": {}}]},
        {"role": "user", "content": "[Системное: служебная пометка]"},
    ]
    # мультимодальный список и [Системное…] пропускаются
    assert guard.last_user_text(messages) == "нормальный вопрос"


async def test_short_reply_not_checked(monkeypatch):
    called = False

    async def _boom(*a, **k):
        nonlocal called
        called = True
        raise AssertionError("не должно вызываться")

    monkeypatch.setattr(guard.client, "chat", _boom)
    on_topic, usage = await guard.is_on_topic("вопрос", "ок 👍", "m")
    assert on_topic is True and usage is None and called is False


async def test_offtopic_detected(monkeypatch):
    async def _chat(messages, model, tools=None):
        return _FakeResult(content="OFFTOPIC")

    monkeypatch.setattr(guard.client, "chat", _chat)
    reply = "С днюхой, бро! " + "рассказ про шлюзы и логи " * 10
    on_topic, usage = await guard.is_on_topic("а для диеты че лучше", reply, "m")
    assert on_topic is False
    assert usage is not None  # проверка учитывается в биллинге


async def test_on_topic_passes(monkeypatch):
    async def _chat(messages, model, tools=None):
        return _FakeResult(content="OK")

    monkeypatch.setattr(guard.client, "chat", _chat)
    reply = "Для диеты лучше яйца всмятку — " + "меньше калорий и больше пользы " * 8
    on_topic, _ = await guard.is_on_topic("а для диеты че лучше", reply, "m")
    assert on_topic is True


async def test_check_failure_is_fail_open(monkeypatch):
    async def _chat(messages, model, tools=None):
        raise RuntimeError("llm упал")

    monkeypatch.setattr(guard.client, "chat", _chat)
    reply = "длинный ответ " * 30
    on_topic, usage = await guard.is_on_topic("вопрос", reply, "m")
    # сбой проверки не должен блокировать нормальный ответ
    assert on_topic is True and usage is None
