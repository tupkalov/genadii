"""LLM-инструменты управления скиллами: «создай скилл, который …» — бот
оформляет сам. Запуск скилла — через очередь задач (без рекурсии в одном ходе).
"""

from app.db.models import Skill
from app.services import audit
from app.services import skills as skills_service
from app.tools.registry import Tool, ToolContext, register


async def _create_skill(
    ctx: ToolContext,
    name: str,
    instruction: str,
    allowed_tools: list[str] | None = None,
) -> str:
    name = name.strip().lower()
    error = skills_service.validate_name(name)
    if error:
        return f"Ошибка: {error}"
    if await skills_service.get_by_name(ctx.session, ctx.workspace, name) is not None:
        return f"Скилл «{name}» уже существует — используй edit_skill."
    skill = Skill(
        workspace_id=ctx.workspace.id,
        name=name,
        instruction=instruction.strip(),
        allowed_tools=allowed_tools,
        created_by_id=ctx.user.id,
    )
    ctx.session.add(skill)
    await ctx.session.flush()
    await audit.log(
        ctx.session,
        action="skill_created",
        payload={"name": name, "via": "tool"},
        workspace_id=ctx.workspace.id,
        user_id=ctx.user.id,
    )
    tools_note = (
        ", ".join(allowed_tools) if allowed_tools else "все инструменты чата"
    )
    return (
        f"Скилл «{name}» создан. Запуск: /{name}. Доступные ему инструменты: "
        f"{tools_note}."
    )


async def _edit_skill(
    ctx: ToolContext,
    name: str,
    instruction: str | None = None,
    allowed_tools: list[str] | None = None,
) -> str:
    skill = await skills_service.get_by_name(
        ctx.session, ctx.workspace, name.strip().lower()
    )
    if skill is None:
        return f"Скилла «{name}» нет в этом чате."
    if instruction:
        skill.instruction = instruction.strip()
    if allowed_tools is not None:
        skill.allowed_tools = allowed_tools or None  # [] → снять ограничения нельзя случайно
    await audit.log(
        ctx.session,
        action="skill_edited",
        payload={"name": skill.name, "via": "tool"},
        workspace_id=ctx.workspace.id,
        user_id=ctx.user.id,
    )
    return f"Скилл «{skill.name}» обновлён."


async def _list_skills(ctx: ToolContext) -> str:
    items = await skills_service.list_all(ctx.session, ctx.workspace)
    if not items:
        return "Скиллов в этом чате нет."
    return "Скиллы чата:\n" + "\n".join(
        f"- /{s.name}{' (выключен)' if not s.enabled else ''}: {s.instruction[:100]}"
        for s in items
    )


async def _run_skill(ctx: ToolContext, name: str, input_text: str | None = None) -> str:
    skill = await skills_service.get_by_name(
        ctx.session, ctx.workspace, name.strip().lower()
    )
    if skill is None:
        return f"Скилла «{name}» нет в этом чате."
    if not skill.enabled:
        return f"Скилл «{skill.name}» выключен."
    task = skills_service.enqueue_run(ctx.session, skill, ctx.user.id, input_text)
    await ctx.session.flush()
    await audit.log(
        ctx.session,
        action="skill_run",
        payload={"name": skill.name, "via": "tool", "task_id": task.id},
        workspace_id=ctx.workspace.id,
        user_id=ctx.user.id,
    )
    return (
        f"Запустил скилл «{skill.name}» (задача #{task.id}) — результат придёт "
        "в чат отдельным сообщением в течение ~20 секунд."
    )


register(
    Tool(
        name="create_skill",
        description=(
            "Создать скилл — именованный сценарий этого чата (инструкция + "
            "опциональный список разрешённых инструментов). Пользователь "
            "запускает его командой /имя, скилл можно привязать к вебхуку "
            "или расписанию. Используй, когда просят «создай скилл/сценарий»."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Имя: латиница/цифры/дефис, 2-32 символа",
                },
                "instruction": {
                    "type": "string",
                    "description": "Что делать при запуске (подробная инструкция)",
                },
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Разрешённые инструменты (имена или маски вида mcp_x_*); "
                        "не указан — все инструменты чата"
                    ),
                },
            },
            "required": ["name", "instruction"],
        },
        handler=_create_skill,
        default_enabled=True,
    )
)

register(
    Tool(
        name="edit_skill",
        description="Изменить инструкцию и/или список инструментов существующего скилла.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "instruction": {"type": "string", "description": "Новая инструкция"},
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Новый список разрешённых инструментов/масок",
                },
            },
            "required": ["name"],
        },
        handler=_edit_skill,
        default_enabled=True,
    )
)

register(
    Tool(
        name="list_skills",
        description="Список скиллов этого чата.",
        parameters={"type": "object", "properties": {}},
        handler=_list_skills,
        default_enabled=True,
    )
)

register(
    Tool(
        name="run_skill",
        description=(
            "Запустить скилл этого чата (асинхронно, результат придёт отдельным "
            "сообщением). input_text — входные данные для скилла."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "input_text": {"type": "string"},
            },
            "required": ["name"],
        },
        handler=_run_skill,
        hourly_limit=30,
        default_enabled=True,
    )
)
