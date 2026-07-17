"""Хартбит: тихие часы, сентинел молчания, гейты should_run."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import heartbeat


def _ws(**settings):
    return SimpleNamespace(id=1, type=SimpleNamespace(), settings=dict(settings))


# --- Тихие часы (интервал через полночь 22→9) ---------------------------------


@pytest.mark.parametrize(
    "hour,expected",
    [(23, True), (3, True), (8, True), (9, False), (12, False), (21, False), (22, True)],
)
def test_quiet_hours_overnight(hour, expected):
    now = datetime(2026, 7, 17, hour, 0)
    assert heartbeat.is_quiet_hours(now, 22, 9) is expected


def test_quiet_hours_same_start_end_disabled():
    assert heartbeat.is_quiet_hours(datetime(2026, 7, 17, 3, 0), 9, 9) is False


# --- Сентинел молчания --------------------------------------------------------


@pytest.mark.parametrize(
    "text,silent",
    [
        ("МОЛЧУ", True),
        ("молчу", True),
        ("SILENCE", True),
        ("  МОЛЧУ.  ", True),
        ("", True),
        ("   ", True),
        ("Привет! Как прошло собеседование? 🙂", False),
        # длинная живая реплика, где слово встретилось случайно, — не глушим
        ("Я не молчу просто так, вот что нашёл по твоей задаче: ...", False),
    ],
)
def test_is_silence(text, silent):
    assert heartbeat.is_silence(text) is silent


# --- enabled_for / интервал ---------------------------------------------------


def test_enabled_for_default_on():
    assert heartbeat.enabled_for(_ws()) is True  # дефолт из конфига — включён


def test_enabled_for_explicit_off():
    assert heartbeat.enabled_for(_ws(heartbeat=False)) is False


def test_interval_override():
    assert heartbeat.interval_minutes(_ws(heartbeat_interval=240)) == 240
    assert heartbeat.interval_minutes(_ws()) == 180  # дефолт


# --- due_to_reflect -----------------------------------------------------------


def test_due_no_last_reflection():
    assert heartbeat.due_to_reflect(_ws(), datetime.now(timezone.utc)) is True


def test_due_recent_reflection_blocks():
    now = datetime.now(timezone.utc)
    ws = _ws(heartbeat_last=(now - timedelta(minutes=30)).isoformat())
    assert heartbeat.due_to_reflect(ws, now) is False


def test_due_old_reflection_passes():
    now = datetime.now(timezone.utc)
    ws = _ws(heartbeat_last=(now - timedelta(hours=4)).isoformat())
    assert heartbeat.due_to_reflect(ws, now) is True


# --- build_instruction --------------------------------------------------------


def test_build_instruction_includes_tasks():
    note = "Ближайшие задачи/напоминания этого чата:\n- 18.07 10:00: врач"
    text = heartbeat.build_instruction(note)
    assert "МОЛЧУ" in text  # сентинел объяснён модели
    assert "врач" in text


def test_build_instruction_without_tasks():
    text = heartbeat.build_instruction("")
    assert "МОЛЧУ" in text


# --- should_run: гейты (стабим БД-хелперы) ------------------------------------

_DAYTIME = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)  # 15:00 MSK
_NIGHT = datetime(2026, 7, 17, 20, 0, tzinfo=timezone.utc)  # 23:00 MSK


@pytest.fixture
def stub_db(monkeypatch):
    """По умолчанию: последнее сообщение 2ч до _DAYTIME, бюджет не исчерпан.
    Время фиксированное (не now()), чтобы совпадать с передаваемым now_utc."""
    async def _last(session, ws):
        return _DAYTIME - timedelta(hours=2)

    async def _budget(session, ws):
        return (False, 0.0, 0.0)

    monkeypatch.setattr(heartbeat, "_last_message_at", _last)
    monkeypatch.setattr(heartbeat.budget_service, "check", _budget)


async def test_should_run_passes(stub_db):
    assert await heartbeat.should_run(None, _ws(), _DAYTIME) is True


async def test_should_run_blocked_when_disabled(stub_db):
    assert await heartbeat.should_run(None, _ws(heartbeat=False), _DAYTIME) is False


async def test_should_run_blocked_not_due(stub_db):
    ws = _ws(heartbeat_last=(_DAYTIME - timedelta(minutes=10)).isoformat())
    assert await heartbeat.should_run(None, ws, _DAYTIME) is False


async def test_should_run_blocked_quiet_hours(stub_db):
    assert await heartbeat.should_run(None, _ws(), _NIGHT) is False


async def test_should_run_blocked_recent_message(monkeypatch, stub_db):
    async def _recent(session, ws):
        return _DAYTIME - timedelta(minutes=5)

    monkeypatch.setattr(heartbeat, "_last_message_at", _recent)
    assert await heartbeat.should_run(None, _ws(), _DAYTIME) is False


async def test_should_run_blocked_empty_chat(monkeypatch, stub_db):
    async def _none(session, ws):
        return None

    monkeypatch.setattr(heartbeat, "_last_message_at", _none)
    assert await heartbeat.should_run(None, _ws(), _DAYTIME) is False


async def test_should_run_blocked_over_budget(monkeypatch, stub_db):
    async def _over(session, ws):
        return (True, 5.0, 5.0)

    monkeypatch.setattr(heartbeat.budget_service, "check", _over)
    assert await heartbeat.should_run(None, _ws(), _DAYTIME) is False
