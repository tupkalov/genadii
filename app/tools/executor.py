import json
import logging

from redis.asyncio import Redis

from app.config import get_settings
from app.services import audit
from app.tools.registry import TOOLS, ToolContext

logger = logging.getLogger("gennady.tools")

RESULT_AUDIT_LIMIT = 500

_redis = Redis.from_url(get_settings().redis_url)


async def _rate_limited(user_id: int, tool_name: str, limit: int) -> bool:
    """Скользящее часовое окно на пользователя+инструмент. True — лимит исчерпан."""
    key = f"toollimit:{user_id}:{tool_name}"
    count = await _redis.incr(key)
    if count == 1:
        await _redis.expire(key, 3600)
    return count > limit


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
    elif tool.hourly_limit and await _rate_limited(
        ctx.user.id, tool.name, tool.hourly_limit
    ):
        result = (
            f"Лимит на «{name}» исчерпан ({tool.hourly_limit}/час у пользователя). "
            "Скажи пользователю подождать."
        )
    else:
        try:
            result = await tool.handler(ctx, **args)
        except Exception as exc:  # noqa: BLE001 — ошибку возвращаем модели
            logger.exception("Tool %s failed (workspace=%s)", name, ctx.workspace.id)
            result = (
                f"Ошибка выполнения «{name}»: {exc}\n"
                "[Разберись с причиной и повтори вызов прямо сейчас. Отвечать "
                "выдуманными данными вместо результата ЗАПРЕЩЕНО; не вышло — "
                "покажи пользователю эту ошибку как есть.]"
            )

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
