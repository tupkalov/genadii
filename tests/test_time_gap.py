"""Маркер паузы в истории: модель должна чувствовать разрывы во времени."""
import pytest

from app.services.llm_chat import (
    gap_note,
    mark_smart,
    strip_leading_timestamp,
    strip_smart_mark,
)


def test_mark_smart_appends_only_when_escalated():
    assert mark_smart("Готово", True) == "Готово 🧠"
    assert mark_smart("Готово", False) == "Готово"
    assert mark_smart("", True) == ""  # пустой не метим
    assert mark_smart("Уже 🧠", True) == "Уже 🧠"  # не дублируем


def test_strip_smart_mark_roundtrip():
    assert strip_smart_mark("Готово 🧠") == "Готово"
    assert strip_smart_mark("Готово") == "Готово"
    assert strip_smart_mark("текст 🧠 в середине не трогаем") == (
        "текст 🧠 в середине не трогаем"
    )


@pytest.mark.parametrize(
    "raw,clean",
    [
        ("[20.07 17:29] Понг! 🏓", "Понг! 🏓"),
        ("  [01.01 09:05]  привет", "привет"),
        ("[20.07 17:29] [20.07 17:30] дубль", "дубль"),  # несколько меток
        ("обычный ответ", "обычный ответ"),
        ("ответ с [20.07 17:29] в середине", "ответ с [20.07 17:29] в середине"),
        ("", ""),
    ],
)
def test_strip_leading_timestamp(raw, clean):
    assert strip_leading_timestamp(raw) == clean


@pytest.mark.parametrize("minutes", [0, 5, 60, 120, 179])
def test_no_note_for_continuous_talk(minutes):
    assert gap_note(minutes * 60) is None


def test_note_at_threshold():
    assert gap_note(180 * 60) == "[⏳ пауза в разговоре: прошло ~3 ч]"


@pytest.mark.parametrize(
    "hours,expected_fragment",
    [
        (3, "~3 ч"),
        (15, "~15 ч"),   # реальный случай: утренняя задача vs вчерашний тред
        (24, "~24 ч"),
        (46, "~46 ч"),
        (47, "~2 дн"),   # с ~2 суток переходим на дни
        (60, "~2 дн"),
        (24 * 15, "~15 дн"),
    ],
)
def test_hours_and_days_formatting(hours, expected_fragment):
    assert expected_fragment in gap_note(hours * 3600)
