"""Инструмент: бот сам меняет свою инициативность в этом чате.

Чтобы на просьбу словами («не пиши мне сам», «заходи почаще») бот реально
переключил параметр, а не просто подсказал команду. Меняет только текущий чат
(изоляция по воркспейсу). Пульс (/heartbeat) не трогает — только субъектность.
"""
from app.services import audit
from app.tools.registry import Tool, ToolContext, register


async def _set_initiative(ctx: ToolContext, percent: int) -> str:
    try:
        value = max(0, min(100, int(percent)))
    except (TypeError, ValueError):
        return "Ошибка: percent должен быть числом 0–100."

    ctx.workspace.settings = {**(ctx.workspace.settings or {}), "initiative": value}
    await audit.log(
        ctx.session,
        action="initiative_set_by_bot",
        payload={"initiative": value},
        workspace_id=ctx.workspace.id,
        user_id=ctx.user.id,
    )
    if value == 0:
        return (
            "Готово: инициативность 0% — сам писать первым в этом чате больше не "
            "буду, только когда позовёшь. Вернуть можно /initiative."
        )
    return (
        f"Готово: инициативность этого чата теперь {value}%. "
        "Изменить в любой момент — /initiative."
    )


register(
    Tool(
        name="set_initiative",
        description=(
            "Изменить, насколько сам инициируешь разговор в ЭТОМ чате (0–100%). "
            "Вызывай, когда пользователь просит словами: «не пиши мне сам / "
            "перестань сам писать» → percent=0; «пиши пореже» → меньше; «заходи "
            "почаще / будь поактивнее» → больше. Пиши первым ты по таймеру-"
            "хартбиту; этот параметр — вероятность и спонтанность таких сообщений. "
            "После вызова кратко подтверди человеку."
        ),
        parameters={
            "type": "object",
            "properties": {
                "percent": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "0 — совсем не писать первым; 30 — изредка; 80 — часто.",
                }
            },
            "required": ["percent"],
        },
        handler=_set_initiative,
        default_enabled=True,
    )
)
