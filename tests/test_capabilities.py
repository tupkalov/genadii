import re

from app.bot.commands import ADMIN_COMMANDS, COMMON_COMMANDS
from app.llm.capabilities import CAPABILITIES
from app.tools.registry import TOOLS


def test_bot_help_tool_registered_and_returns_capabilities():
    tool = TOOLS.get("bot_help")
    assert tool is not None
    assert tool.default_enabled is True


def test_key_commands_mentioned():
    for cmd in ("/skill", "/mcp add", "/hook add", "/undo", "/forget", "/retry"):
        assert cmd in CAPABILITIES, cmd


def test_all_menu_commands_mentioned():
    """Защита от рассинхрона: новая команда в меню обязана попасть в bot_help."""
    for c in COMMON_COMMANDS + ADMIN_COMMANDS:
        assert f"/{c.command}" in CAPABILITIES, f"/{c.command} нет в CAPABILITIES"


def test_no_html_tags():
    # Текст уходит модели как plain/markdown; HTML-теги она бы скопировала в ответ
    assert not re.search(r"<(b|i|code|pre)>", CAPABILITIES)
