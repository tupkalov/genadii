from datetime import datetime, timezone

from app.services import reminders
from app.tools.registry import Tool, ToolContext, register


def _resolve_schedule(run_at: str | None, cron: str | None):
    """(run_at_utc, cron, error) из аргументов LLM."""
    if cron:
        if not reminders.validate_cron(cron):
            return None, None, f"Ошибка: «{cron}» — невалидное cron-выражение (5 полей)."
        return reminders.next_run_from_cron(cron), cron, None
    if not run_at:
        return None, None, "Ошибка: укажи run_at или cron."
    try:
        run_at_utc = reminders.parse_local(run_at)
    except ValueError:
        return None, None, f"Ошибка: «{run_at}» не является датой ISO (YYYY-MM-DDTHH:MM)."
    if run_at_utc <= datetime.now(timezone.utc):
        return None, None, "Ошибка: это время уже в прошлом. Уточни у пользователя."
    return run_at_utc, None, None


SCHEDULE_PARAMS = {
    "run_at": {
        "type": "string",
        "description": "Разовое срабатывание: ISO YYYY-MM-DDTHH:MM, локальное время чата",
    },
    "cron": {
        "type": "string",
        "description": "Повторяющееся: cron из 5 полей, напр. «0 9 * * *» = каждый день в 9:00",
    },
}


async def _remind(
    ctx: ToolContext, text: str, run_at: str | None = None, cron: str | None = None
) -> str:
    run_at_utc, cron_expr, error = _resolve_schedule(run_at, cron)
    if error:
        return error
    task = await reminders.create(
        ctx.session, ctx.workspace, ctx.user, text, run_at_utc, "reminder", cron_expr
    )
    when = f"по расписанию «{cron_expr}», ближайшее" if cron_expr else "на"
    return f"Напоминание #{task.id} создано {when} {reminders.format_local(task.run_at)}: {text}"


async def _schedule_task(
    ctx: ToolContext, instruction: str, run_at: str | None = None, cron: str | None = None
) -> str:
    run_at_utc, cron_expr, error = _resolve_schedule(run_at, cron)
    if error:
        return error
    task = await reminders.create(
        ctx.session, ctx.workspace, ctx.user, instruction, run_at_utc, "agent_task", cron_expr
    )
    when = f"по расписанию «{cron_expr}», ближайший запуск" if cron_expr else "на"
    return f"Задача #{task.id} запланирована {when} {reminders.format_local(task.run_at)}: {instruction}"


register(
    Tool(
        name="remind",
        description=(
            "Прислать в чат напоминание с заданным текстом (без размышлений). "
            "Вычисли время из слов пользователя, опираясь на текущее время из "
            "системного промпта. Для повторяющихся — cron."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Текст напоминания"},
                **SCHEDULE_PARAMS,
            },
            "required": ["text"],
        },
        handler=_remind,
        default_enabled=True,
    )
)

register(
    Tool(
        name="schedule_task",
        description=(
            "Запланировать СЕБЕ задачу: в назначенное время ты проснёшься, выполнишь "
            "инструкцию (можешь использовать инструменты и контекст чата) и напишешь "
            "результат в чат. Для простого «напомни текстом» используй remind."
        ),
        parameters={
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "Что сделать при пробуждении (подробная инструкция)",
                },
                **SCHEDULE_PARAMS,
            },
            "required": ["instruction"],
        },
        handler=_schedule_task,
        default_enabled=True,
    )
)
