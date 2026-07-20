"""Команда /model: два тира (workhorse/smart) × два уровня (чат/глобально).

- /model — статус (оба тира + источник)
- /model list — каталог (что можно ставить, с ценами и потолком)
- /model <id> — запиннить чат на одну модель (workhorse=smart, без роутера)
- /model workhorse <id> | /model smart <id> — тир для этого чата
- /model reset — снять оверрайды чата
- /model default [workhorse|smart] <id> | /model default reset — глобально (админ)

Участники могут ставить модель НЕ дороже дефолта своего тира (потолок по
блендованной цене). Админ — без ограничений. При удешевлении глобального
дефолта частные оверрайды дороже него автопонижаются (логируется).
"""
import html

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserRole, Workspace
from app.services import app_settings, audit, messages, models_catalog

router = Router(name="model")


def _esc(s: str) -> str:
    return html.escape(s or "")


async def _effective(session: AsyncSession, workspace: Workspace) -> tuple[str, str, bool, bool]:
    """(workhorse, smart, workhorse_свой?, smart_свой?)."""
    s = workspace.settings or {}
    wh_own = s.get("workhorse") or s.get("model_override")
    sm_own = s.get("smart")
    wh = wh_own or await app_settings.workhorse_default(session)
    sm = sm_own or await app_settings.smart_default(session)
    return wh, sm, bool(wh_own), bool(sm_own)


async def _price_note(session: AsyncSession, model_id: str) -> str:
    row = await models_catalog.get(session, model_id)
    if row is None:
        return ""
    return f" (${float(row.price_in):.2f}/${float(row.price_out):.2f} за 1M)"


async def _status_text(session: AsyncSession, workspace: Workspace) -> str:
    wh, sm, wh_own, sm_own = await _effective(session, workspace)
    return (
        "🧠 <b>Модели этого чата</b>\n"
        f"• workhorse (простое): <code>{_esc(wh)}</code>"
        f"{await _price_note(session, wh)} {'(свой)' if wh_own else '(дефолт)'}\n"
        f"• smart (решения): <code>{_esc(sm)}</code>"
        f"{await _price_note(session, sm)} {'(свой)' if sm_own else '(дефолт)'}\n\n"
        "Сменить для чата: <code>/model workhorse vendor/model</code>, "
        "<code>/model smart vendor/model</code>, <code>/model reset</code>\n"
        "Одна модель на всё: <code>/model vendor/model</code>\n"
        "Список и цены: <code>/model list</code>\n"
        "Участникам — только не дороже дефолта. Глобально (админ): "
        "<code>/model default workhorse vendor/model</code>."
    )


async def _list_text(session: AsyncSession, workspace: Workspace) -> str:
    wh_cap, sm_cap, _, _ = await _effective(session, workspace)
    rows = await models_catalog.cheapest(session, limit=15)
    if not rows:
        return "Каталог пуст — синк ещё не прошёл. Загляни через минуту."
    cap_score = await models_catalog.score(session, wh_cap)
    lines = ["🗂 <b>Модели (дешёвые сверху)</b>  — ✓ можно участнику (≤ workhorse-дефолта):", ""]
    for r in rows:
        ok = cap_score is not None and models_catalog.blended(r.price_in, r.price_out) <= cap_score + 1e-9
        mark = "✓" if ok else "•"
        lines.append(
            f"{mark} <code>{_esc(r.id)}</code> — ${float(r.price_in):.2f}/${float(r.price_out):.2f}"
        )
    lines.append("")
    lines.append("Полный каталог — на openrouter.ai/models. Ставь по точному id.")
    return "\n".join(lines)


async def _reply(message, session, workspace, text):
    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)


async def _set_chat_tier(
    session, workspace, user, model_id: str, tier: str, cap_model: str
) -> str:
    """tier: 'workhorse' | 'smart' | 'both'. cap_model — дефолт для потолка."""
    model_id = model_id.strip()
    if not await models_catalog.is_known(session, model_id):
        return f"Не знаю модель <code>{_esc(model_id)}</code>. Смотри <code>/model list</code>."
    if user.role != UserRole.admin and not await models_catalog.within_cap(
        session, model_id, cap_model
    ):
        return (
            f"Модель <code>{_esc(model_id)}</code> дороже дефолта "
            f"(<code>{_esc(cap_model)}</code>) — участникам можно только не дороже. "
            "Что доступно — в <code>/model list</code> (со ✓)."
        )
    new = dict(workspace.settings or {})
    if tier == "both":
        new["workhorse"] = new["smart"] = model_id
        new.pop("model_override", None)
        desc = "на одну модель (без роутера)"
    else:
        new[tier] = model_id
        desc = f"{tier}"
    workspace.settings = new
    await audit.log(
        session, action="model_set",
        payload={"tier": tier, "model": model_id},
        workspace_id=workspace.id, user_id=user.id,
    )
    return f"🧠 Чат переключён ({desc}): <code>{_esc(model_id)}</code>"


async def _set_global_tier(session, user, model_id: str, tier: str) -> str:
    model_id = model_id.strip()
    if not await models_catalog.is_known(session, model_id):
        return f"Не знаю модель <code>{_esc(model_id)}</code>. Смотри <code>/model list</code>."
    await app_settings.set_tier_default(session, tier, model_id)
    changes = await models_catalog.reconcile_overrides(session, tier, model_id)
    for c in changes:
        await audit.log(
            session, action="model_autodowngrade", payload=c, workspace_id=c["workspace_id"]
        )
    await audit.log(
        session, action="model_default_set",
        payload={"tier": tier, "model": model_id}, user_id=user.id,
    )
    extra = f" Автопонижено чатов: {len(changes)}." if changes else ""
    return f"🌍 Глобальный дефолт {tier}: <code>{_esc(model_id)}</code>.{extra}"


@router.message(Command("model"))
async def cmd_model(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    parts = (command.args or "").split()
    low = parts[0].lower() if parts else ""

    # --- справка/список ---
    if not parts:
        return await _reply(message, session, workspace, await _status_text(session, workspace))
    if low == "list":
        return await _reply(message, session, workspace, await _list_text(session, workspace))

    # --- глобально (админ) ---
    if low == "default":
        if user.role != UserRole.admin:
            return await _reply(message, session, workspace, "Глобальный дефолт меняет только админ. 🙅")
        rest = parts[1:]
        if not rest:
            wh = await app_settings.workhorse_default(session)
            sm = await app_settings.smart_default(session)
            text = (
                f"🌍 Глобальные дефолты:\n• workhorse: <code>{_esc(wh)}</code>\n"
                f"• smart: <code>{_esc(sm)}</code>\n\n"
                "Сменить: <code>/model default workhorse vendor/model</code> "
                "(или smart). Сброс: <code>/model default reset</code>."
            )
            return await _reply(message, session, workspace, text)
        if rest[0].lower() == "reset":
            await app_settings.reset_tier_default(session, "workhorse")
            await app_settings.reset_tier_default(session, "smart")
            return await _reply(message, session, workspace, "🌍 Глобальные дефолты сброшены к конфигу.")
        if rest[0].lower() in ("workhorse", "smart"):
            if len(rest) < 2:
                return await _reply(message, session, workspace, "Формат: <code>/model default workhorse vendor/model</code>.")
            text = await _set_global_tier(session, user, rest[1], rest[0].lower())
            return await _reply(message, session, workspace, text)
        # /model default <id> → workhorse
        text = await _set_global_tier(session, user, rest[0], "workhorse")
        return await _reply(message, session, workspace, text)

    # --- для чата ---
    if low == "reset":
        new = dict(workspace.settings or {})
        for k in ("workhorse", "smart", "model_override"):
            new.pop(k, None)
        workspace.settings = new
        await audit.log(session, action="model_set", payload={"reset": True},
                        workspace_id=workspace.id, user_id=user.id)
        return await _reply(message, session, workspace, "🧠 Оверрайды чата сняты — наследуем глобальный дефолт.")

    wh_default = await app_settings.workhorse_default(session)
    sm_default = await app_settings.smart_default(session)

    if low in ("workhorse", "smart"):
        if len(parts) < 2:
            return await _reply(message, session, workspace, f"Формат: <code>/model {low} vendor/model</code>.")
        cap = sm_default if low == "smart" else wh_default
        text = await _set_chat_tier(session, workspace, user, parts[1], low, cap)
        return await _reply(message, session, workspace, text)

    # /model <id> → пин обоих тиров (потолок — по workhorse-дефолту)
    text = await _set_chat_tier(session, workspace, user, parts[0], "both", wh_default)
    await _reply(message, session, workspace, text)
