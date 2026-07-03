import json
import logging

from app.services import audit
from app.tools.registry import TOOLS, ToolContext

logger = logging.getLogger("gennady.tools")

RESULT_AUDIT_LIMIT = 500


async def execute_tool_call(ctx: ToolContext, tool_call: dict) -> str:
    """Выполняет один tool call от LLM; каждый вызов — в audit_log."""
    name = tool_call.get("function", {}).get("name", "")
    raw_args = tool_call.get("function", {}).get("arguments") or "{}"

    tool = TOOLS.get(name)
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError:
        args = None

    if tool is None:
        result = f"Ошибка: инструмент «{name}» не существует."
    elif args is None:
        result = "Ошибка: аргументы не являются валидным JSON."
    else:
        try:
            result = await tool.handler(ctx, **args)
        except Exception as exc:  # noqa: BLE001 — ошибку возвращаем модели
            logger.exception("Tool %s failed (workspace=%s)", name, ctx.workspace.id)
            result = f"Ошибка выполнения «{name}»: {exc}"

    await audit.log(
        ctx.session,
        action="tool_call",
        payload={
            "tool": name,
            "args": args if args is not None else raw_args[:200],
            "result": result[:RESULT_AUDIT_LIMIT],
        },
        workspace_id=ctx.workspace.id,
        user_id=ctx.user.id,
    )
    return result
