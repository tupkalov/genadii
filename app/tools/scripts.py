import re

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import SavedScript
from app.tools.registry import Tool, ToolContext, register
from app.tools.sandbox import CODE_LIMIT, _run_python

NAME_RE = re.compile(r"^[a-z0-9_-]{1,64}$")


def _normalize_name(name: str) -> str | None:
    name = re.sub(r"[^a-z0-9_-]", "-", name.strip().lower()).strip("-")[:64]
    return name if NAME_RE.match(name) else None


async def _get_script(ctx: ToolContext, name: str) -> SavedScript | None:
    # Скрипты строго изолированы per-workspace
    return await ctx.session.scalar(
        select(SavedScript).where(
            SavedScript.workspace_id == ctx.workspace.id,
            SavedScript.name == name,
        )
    )


async def _save_script(
    ctx: ToolContext, name: str, code: str, description: str | None = None
) -> str:
    normalized = _normalize_name(name)
    if normalized is None:
        return "Ошибка: имя — латиница/цифры/дефис/подчёркивание, до 64 символов."
    if len(code) > CODE_LIMIT:
        return f"Ошибка: код длиннее {CODE_LIMIT} символов."

    await ctx.session.execute(
        pg_insert(SavedScript)
        .values(
            workspace_id=ctx.workspace.id,
            name=normalized,
            code=code,
            description=description,
            created_by_id=ctx.user.id,
        )
        .on_conflict_do_update(
            index_elements=["workspace_id", "name"],
            set_={"code": code, "description": description, "updated_at": func.now()},
        )
    )
    return f"Скрипт «{normalized}» сохранён в этом чате."


async def _run_saved_script(ctx: ToolContext, name: str) -> str:
    normalized = _normalize_name(name) or name
    script = await _get_script(ctx, normalized)
    if script is None:
        names = (
            await ctx.session.scalars(
                select(SavedScript.name).where(
                    SavedScript.workspace_id == ctx.workspace.id
                )
            )
        ).all()
        available = ", ".join(names) if names else "нет ни одного"
        return f"Скрипта «{name}» нет. Доступные: {available}."
    return await _run_python(ctx, script.code)


async def _list_scripts(ctx: ToolContext) -> str:
    scripts = (
        await ctx.session.scalars(
            select(SavedScript)
            .where(SavedScript.workspace_id == ctx.workspace.id)
            .order_by(SavedScript.name)
        )
    ).all()
    if not scripts:
        return "В этом чате нет сохранённых скриптов."
    return "Сохранённые скрипты:\n" + "\n".join(
        f"- {s.name}: {s.description or 'без описания'}" for s in scripts
    )


register(
    Tool(
        name="save_script",
        description=(
            "Сохранить Python-скрипт под именем для переиспользования в этом чате "
            "(в т.ч. с зашитыми туда секретами/токенами, если их дал пользователь — "
            "это личный чат). Используй, когда пользователь просит запомнить/сохранить "
            "получившийся скрипт. Сначала проверь код через run_python."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Имя: латиница/цифры/дефис"},
                "code": {"type": "string", "description": "Python-код целиком"},
                "description": {
                    "type": "string",
                    "description": "Короткое описание, что делает скрипт",
                },
            },
            "required": ["name", "code"],
        },
        handler=_save_script,
        default_enabled=True,
    )
)

register(
    Tool(
        name="run_saved_script",
        description=(
            "Запустить сохранённый скрипт этого чата по имени (в песочнице). "
            "Аргументов нет: для действий с параметром («добавь задачу X») "
            "выполняй run_python, подставив параметр прямо в код."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Имя сохранённого скрипта"}
            },
            "required": ["name"],
        },
        handler=_run_saved_script,
        default_enabled=True,
    )
)

register(
    Tool(
        name="list_scripts",
        description="Список сохранённых скриптов этого чата.",
        parameters={"type": "object", "properties": {}},
        handler=_list_scripts,
        default_enabled=True,
    )
)
