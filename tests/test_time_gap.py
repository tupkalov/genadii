"""Маркер паузы в истории: модель должна чувствовать разрывы во времени."""
import pytest

from app.services.llm_chat import gap_note


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
