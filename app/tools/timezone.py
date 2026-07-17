"""Инструмент: бот запоминает часовой пояс этого чата.

Нужен, чтобы «тихие часы» хартбита (ночью не писать) считались по времени
пользователя, а не по серверному дефолту. Бот сам вызывает, когда узнаёт, где
человек («я в Подгорице», «у нас сейчас 2 ночи»), подставляя IANA-пояс. Меняет
только текущий чат (изоляция по воркспейсу).
"""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services import audit
from app.tools.registry import Tool, ToolContext, register


async def _set_timezone(ctx: ToolContext, tz: str) -> str:
    tz = (tz or "").strip()
    try:
        ZoneInfo(tz)  # валидация IANA-имени
    except (ZoneInfoNotFoundError, ValueError, ModuleNotFoundError):
        return (
            f"Ошибка: «{tz}» — не похоже на IANA-пояс. Нужен вид "
            "Europe/Podgorica, Europe/Moscow, Asia/Tbilisi."
        )

    ctx.workspace.settings = {**(ctx.workspace.settings or {}), "timezone": tz}
    await audit.log(
        ctx.session,
        action="timezone_set_by_bot",
        payload={"timezone": tz},
        workspace_id=ctx.workspace.id,
        user_id=ctx.user.id,
    )
    return (
        f"Запомнил пояс этого чата: {tz}. Ночью (22:00–09:00 по нему) сам писать "
        "не буду."
    )


register(
    Tool(
        name="set_timezone",
        description=(
            "Запомнить часовой пояс ЭТОГО чата (IANA, напр. Europe/Podgorica). "
            "Вызывай, когда узнаёшь, где человек или сколько у него времени "
            "(«я в Подгорице», «у нас 2 ночи»), — по этому поясу считаются мои "
            "тихие часы, чтобы не писать первым ночью. Определи IANA-пояс по "
            "городу/стране сам. После вызова кратко подтверди."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tz": {
                    "type": "string",
                    "description": "IANA-имя пояса, напр. Europe/Podgorica, Asia/Tbilisi.",
                }
            },
            "required": ["tz"],
        },
        handler=_set_timezone,
        default_enabled=True,
    )
)
