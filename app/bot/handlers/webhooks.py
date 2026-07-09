import html
import secrets

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import delete, select

from app.config import get_settings
from app.db.models import User, Webhook, Workspace
from app.services import audit, messages, skills

router = Router(name="webhooks")

USAGE = (
    "Входящие вебхуки этого чата. Команды:\n"
    "<code>/hook add имя</code> — просто уведомлять о событиях\n"
    "<code>/hook add имя инструкция…</code> — реагировать как агент\n"
    "<code>/hook add имя skill:имя-скилла</code> — обрабатывать скиллом\n"
    "<code>/hook list</code>, <code>/hook on|off имя</code>, "
    "<code>/hook delete имя</code>"
)


def _hook_url(token: str) -> str:
    base = get_settings().webhook_base_url.rstrip("/")
    if base:
        return f"{base}/hooks/{token}"
    return f"/hooks/{token} (задай WEBHOOK_BASE_URL в .env для полного URL)"


async def _get_hook(session, workspace: Workspace, name: str) -> Webhook | None:
    return await session.scalar(
        select(Webhook).where(
            Webhook.workspace_id == workspace.id, Webhook.name == name
        )
    )


async def _cmd_add(session, workspace, user, args: list[str]) -> str:
    if not args:
        return (
            "Формат: <code>/hook add имя [инструкция…]</code>\n"
            "или <code>/hook add имя skill:имя-скилла</code>"
        )
    name = args[0].lower()[:64]
    instruction = " ".join(args[1:]).strip() or None
    if await _get_hook(session, workspace, name) is not None:
        return f"Хук «{html.escape(name)}» уже есть — сначала /hook delete."

    skill_id = None
    if instruction and instruction.startswith("skill:"):
        skill_name = instruction.removeprefix("skill:").strip().lower()
        skill = await skills.get_by_name(session, workspace, skill_name)
        if skill is None:
            return (
                f"Скилла «{html.escape(skill_name)}» нет в этом чате — "
                "сначала создай: /skill add"
            )
        skill_id = skill.id
        instruction = None

    hook = Webhook(
        workspace_id=workspace.id,
        name=name,
        token=secrets.token_urlsafe(24),
        mode="agent" if (instruction or skill_id) else "notify",
        instruction=instruction,
        skill_id=skill_id,
        created_by_id=user.id,
    )
    session.add(hook)
    await session.flush()
    await audit.log(
        session,
        action="webhook_created",
        payload={"name": name, "mode": hook.mode},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    if skill_id:
        mode_note = "агентский — каждое событие обрабатывает скилл"
    elif instruction:
        mode_note = f"агентский — на каждое событие выполню:\n«{html.escape(instruction)}»"
    else:
        mode_note = "уведомления — буду пересылать события в чат"
    return (
        f"Создал хук «{html.escape(name)}» ({mode_note}).\n\n"
        f"POST-адрес:\n<code>{html.escape(_hook_url(hook.token))}</code>"
    )


async def _cmd_list(session, workspace) -> str:
    hooks = (
        await session.scalars(
            select(Webhook)
            .where(Webhook.workspace_id == workspace.id)
            .order_by(Webhook.name)
        )
    ).all()
    if not hooks:
        return "Вебхуков нет.\n" + USAGE
    lines = ["<b>Вебхуки этого чата:</b>"]
    for h in hooks:
        state = "🟢" if h.enabled else "⚪"
        mode = "🤖 агент" if h.mode == "agent" else "🔔 уведомления"
        fired = (
            f", срабатывал {h.fire_count} раз (посл. {h.last_fired_at:%Y-%m-%d %H:%M})"
            if h.fire_count
            else ""
        )
        lines.append(
            f"{state} <b>{html.escape(h.name)}</b> — {mode}{fired}\n"
            f"   <code>{html.escape(_hook_url(h.token))}</code>"
        )
    return "\n".join(lines)


async def _cmd_toggle(session, workspace, user, name: str, enabled: bool) -> str:
    hook = await _get_hook(session, workspace, name)
    if hook is None:
        return f"Хука «{html.escape(name)}» в этом чате нет."
    hook.enabled = enabled
    await audit.log(
        session,
        action="webhook_toggled",
        payload={"name": name, "enabled": enabled},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    return f"«{html.escape(name)}» {'включён 🟢' if enabled else 'выключен ⚪'}"


async def _cmd_delete(session, workspace, user, name: str) -> str:
    hook = await _get_hook(session, workspace, name)
    if hook is None:
        return f"Хука «{html.escape(name)}» в этом чате нет."
    await session.execute(delete(Webhook).where(Webhook.id == hook.id))
    await audit.log(
        session,
        action="webhook_deleted",
        payload={"name": name},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    return f"Удалил хук «{html.escape(name)}»."


@router.message(Command("hook"))
async def cmd_hook(
    message: Message,
    user: User,
    workspace: Workspace,
    session,
    command: CommandObject,
) -> None:
    # Доступно любому участнику воркспейса (whitelist гарантирует middleware);
    # авторство фиксируется в audit_log
    args = (command.args or "").split()
    sub = args[0].lower() if args else "list"
    rest = args[1:]
    if sub == "add":
        text = await _cmd_add(session, workspace, user, rest)
    elif sub == "list":
        text = await _cmd_list(session, workspace)
    elif sub in ("on", "off") and rest:
        text = await _cmd_toggle(session, workspace, user, rest[0].lower(), sub == "on")
    elif sub == "delete" and rest:
        text = await _cmd_delete(session, workspace, user, rest[0].lower())
    else:
        text = USAGE

    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
