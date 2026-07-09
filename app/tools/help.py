from app.llm.capabilities import CAPABILITIES
from app.tools.registry import Tool, ToolContext, register


async def _bot_help(ctx: ToolContext) -> str:
    return CAPABILITIES


register(
    Tool(
        name="bot_help",
        description=(
            "Полное описание твоих собственных возможностей, команд и настроек. "
            "ОБЯЗАТЕЛЬНО вызывай, когда спрашивают «что ты умеешь», «как "
            "настроить …» (вебхук, скилл, MCP, память, напоминания) или про "
            "любую твою команду — не отвечай про свой функционал по памяти."
        ),
        parameters={"type": "object", "properties": {}},
        handler=_bot_help,
        default_enabled=True,
    )
)
