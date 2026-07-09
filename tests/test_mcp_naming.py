import re

from app.services.mcp import sanitize_tool_name

OPENROUTER_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def test_simple_names():
    assert sanitize_tool_name("todoist", "add_task") == "mcp_todoist_add_task"


def test_invalid_chars_replaced():
    name = sanitize_tool_name("srv", "поиск задач.v2")
    assert OPENROUTER_NAME_RE.match(name)
    assert name.startswith("mcp_srv_")


def test_truncated_to_64():
    name = sanitize_tool_name("server", "x" * 100)
    assert len(name) == 64
    assert OPENROUTER_NAME_RE.match(name)


def test_dots_and_spaces():
    assert OPENROUTER_NAME_RE.match(sanitize_tool_name("a-b_c", "get.user info"))
