# Импорт модулей с register(...) наполняет реестр
import app.tools.help  # noqa: F401
import app.tools.history  # noqa: F401
import app.tools.initiative  # noqa: F401
import app.tools.images  # noqa: F401
import app.tools.memory  # noqa: F401
import app.tools.reactions  # noqa: F401
import app.tools.reminders  # noqa: F401
import app.tools.sandbox  # noqa: F401
import app.tools.scripts  # noqa: F401
import app.tools.skills_tools  # noqa: F401
import app.tools.web  # noqa: F401
from app.tools.registry import TOOLS, Tool, ToolContext, register

__all__ = ["TOOLS", "Tool", "ToolContext", "register"]
