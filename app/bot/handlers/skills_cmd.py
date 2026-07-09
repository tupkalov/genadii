import html

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.chat import _generate_and_send
from app.db.models import Skill, User, Workspace
from app.services import audit, messages, reminders, skills

router = Router(name="skills_cmd")
# Слэш-вызов скиллов: отдельный роутер, включается ПОСЛЕДНИМ (после chat)
invoke_router = Router(name="skills_invoke")

USAGE = (
    "Скиллы этого чата — именованные сценарии, вызываются как <code>/имя</code>.\n"
    "<code>/skill add имя инструкция…</code> — создать\n"
    "<code>/skill edit имя новая-инструкция…</code> — переписать\n"
    "<code>/skill tools имя tool1,mcp_x_* | all</code> — ограничить инструменты\n"
    "<code>/skill show имя</code>, <code>/skill list</code>\n"
    "<code>/skill cron имя выражение…</code> — запуск по расписанию (off — снять)\n"
    "<code>/skill on|off имя</code>, <code>/skill remove имя</code>\n"
    "Можно и словами: «создай скилл, который …» — оформлю сам."
)


async def _cmd_add(session, workspace, user, args: list[str]) -> str:
    if len(args) < 2:
        return "Формат: <code>/skill add имя инструкция…</code>"
    name = args[0].lower()
    error = skills.validate_name(name)
    if error:
        return html.escape(error)
    if await skills.get_by_name(session, workspace, name) is not None:
        return f"Скилл «{html.escape(name)}» уже есть — /skill edit для правки."
    instruction = " ".join(args[1:]).strip()

    skill = Skill(
        workspace_id=workspace.id,
        name=name,
        instruction=instruction,
        created_by_id=user.id,
    )
    session.add(skill)
    await session.flush()
    await audit.log(
        session,
        action="skill_created",
        payload={"name": name},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    return (
        f"Создал скилл «{html.escape(name)}». Запуск: <code>/{html.escape(name)}</code>\n"
        "Сейчас ему доступны ВСЕ инструменты чата; ограничить: "
        f"<code>/skill tools {html.escape(name)} список,масок</code>"
    )


async def _cmd_edit(session, workspace, user, args: list[str]) -> str:
    if len(args) < 2:
        return "Формат: <code>/skill edit имя новая-инструкция…</code>"
    skill = await skills.get_by_name(session, workspace, args[0].lower())
    if skill is None:
        return f"Скилла «{html.escape(args[0])}» нет."
    skill.instruction = " ".join(args[1:]).strip()
    await audit.log(
        session,
        action="skill_edited",
        payload={"name": skill.name},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    return f"Обновил инструкцию «{html.escape(skill.name)}»."


async def _cmd_tools(session, workspace, user, args: list[str]) -> str:
    if len(args) < 2:
        return (
            "Формат: <code>/skill tools имя tool1,tool2,mcp_x_*</code> "
            "или <code>/skill tools имя all</code>"
        )
    skill = await skills.get_by_name(session, workspace, args[0].lower())
    if skill is None:
        return f"Скилла «{html.escape(args[0])}» нет."
    spec = " ".join(args[1:]).strip()
    if spec.lower() == "all":
        skill.allowed_tools = None
        note = "все инструменты чата"
    else:
        masks = [m.strip() for m in spec.split(",") if m.strip()]
        skill.allowed_tools = masks
        note = ", ".join(f"<code>{html.escape(m)}</code>" for m in masks) or "никаких"
    await audit.log(
        session,
        action="skill_tools_set",
        payload={"name": skill.name, "allowed_tools": skill.allowed_tools},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    return f"«{html.escape(skill.name)}» теперь может использовать: {note}"


async def _cmd_show(session, workspace, name: str) -> str:
    skill = await skills.get_by_name(session, workspace, name)
    if skill is None:
        return f"Скилла «{html.escape(name)}» нет."
    tools_note = (
        ", ".join(html.escape(m) for m in skill.allowed_tools)
        if skill.allowed_tools is not None
        else "все инструменты чата"
    )
    return (
        f"<b>/{html.escape(skill.name)}</b> {'🟢' if skill.enabled else '⚪'}\n"
        f"Инструменты: {tools_note}\n\n"
        f"<i>{html.escape(skill.instruction)}</i>"
    )


async def _cmd_list(session, workspace) -> str:
    items = await skills.list_all(session, workspace)
    if not items:
        return "Скиллов пока нет.\n" + USAGE
    lines = ["<b>Скиллы этого чата</b> (запуск: /имя):"]
    for s in items:
        state = "🟢" if s.enabled else "⚪"
        guard = "" if s.allowed_tools is None else " 🔒"
        lines.append(
            f"{state} <code>/{html.escape(s.name)}</code>{guard} — "
            f"{html.escape(s.instruction[:80])}…"
            if len(s.instruction) > 80
            else f"{state} <code>/{html.escape(s.name)}</code>{guard} — "
            f"{html.escape(s.instruction)}"
        )
    return "\n".join(lines)


async def _cmd_cron(session, workspace, user, args: list[str]) -> str:
    if len(args) < 2:
        return "Формат: <code>/skill cron имя 0 9 * * *</code> (или off)"
    skill = await skills.get_by_name(session, workspace, args[0].lower())
    if skill is None:
        return f"Скилла «{html.escape(args[0])}» нет."
    expr = " ".join(args[1:]).strip()
    if expr.lower() == "off":
        cancelled = 0
        for task in await reminders.list_pending(session, workspace):
            if (task.payload or {}).get("skill_id") == skill.id and task.cron:
                task.status = "cancelled"
                cancelled += 1
        return f"Снял расписаний скилла «{html.escape(skill.name)}»: {cancelled}."
    if not reminders.validate_cron(expr):
        return f"«{html.escape(expr)}» — не похоже на cron-выражение."
    task = skills.enqueue_run(
        session,
        skill,
        user.id,
        cron=expr,
        run_at=reminders.next_run_from_cron(expr),
    )
    await session.flush()
    await audit.log(
        session,
        action="skill_cron_set",
        payload={"name": skill.name, "cron": expr, "task_id": task.id},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    return (
        f"Скилл «{html.escape(skill.name)}» — по расписанию "
        f"<code>{html.escape(expr)}</code> (задача #{task.id}, "
        f"следующий запуск {reminders.format_local(task.run_at)})."
    )


async def _cmd_toggle(session, workspace, user, name: str, enabled: bool) -> str:
    skill = await skills.get_by_name(session, workspace, name)
    if skill is None:
        return f"Скилла «{html.escape(name)}» нет."
    skill.enabled = enabled
    return f"«{html.escape(skill.name)}» {'включён 🟢' if enabled else 'выключен ⚪'}"


async def _cmd_remove(session, workspace, user, name: str) -> str:
    skill = await skills.get_by_name(session, workspace, name)
    if skill is None:
        return f"Скилла «{html.escape(name)}» нет."
    await session.execute(delete(Skill).where(Skill.id == skill.id))
    await audit.log(
        session,
        action="skill_removed",
        payload={"name": name},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    return f"Удалил скилл «{html.escape(name)}»."


@router.message(Command("skill"))
async def cmd_skill(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    args = (command.args or "").split()
    sub = args[0].lower() if args else "list"
    rest = args[1:]
    if sub == "add":
        text = await _cmd_add(session, workspace, user, rest)
    elif sub == "edit":
        text = await _cmd_edit(session, workspace, user, rest)
    elif sub == "tools":
        text = await _cmd_tools(session, workspace, user, rest)
    elif sub == "show" and rest:
        text = await _cmd_show(session, workspace, rest[0].lower())
    elif sub == "list":
        text = await _cmd_list(session, workspace)
    elif sub == "cron":
        text = await _cmd_cron(session, workspace, user, rest)
    elif sub in ("on", "off") and rest:
        text = await _cmd_toggle(session, workspace, user, rest[0].lower(), sub == "on")
    elif sub == "remove" and rest:
        text = await _cmd_remove(session, workspace, user, rest[0].lower())
    else:
        text = USAGE

    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)


@invoke_router.message(F.text.startswith("/"))
async def invoke_skill(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
) -> None:
    """Слэш-вызов скилла: /имя [аргументы]. Ловит команды, не съеденные
    другими роутерами; незнакомое имя молча игнорируем (как раньше)."""
    parts = message.text[1:].split(maxsplit=1)
    name = parts[0].split("@")[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else None

    skill = await skills.get_by_name(session, workspace, name)
    if skill is None or not skill.enabled:
        return

    await audit.log(
        session,
        action="skill_run",
        payload={"name": skill.name, "via": "slash"},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    await _generate_and_send(
        message,
        user,
        workspace,
        session,
        extra_user_message=skills.build_prompt(skill, argument),
        allowed_tools=skill.allowed_tools,
    )
