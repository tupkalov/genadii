from app.tools.scripts import _normalize_name


def test_lowercases_and_keeps_valid_chars():
    assert _normalize_name("My-Script_1") == "my-script_1"


def test_replaces_invalid_chars_with_dash():
    assert _normalize_name("todoist digest!") == "todoist-digest"


def test_strips_leading_trailing_dashes():
    assert _normalize_name("  !!weird!!  ") == "weird"


def test_truncates_to_64_chars():
    assert len(_normalize_name("a" * 100)) == 64


def test_empty_after_normalization_is_none():
    assert _normalize_name("!!!") is None
