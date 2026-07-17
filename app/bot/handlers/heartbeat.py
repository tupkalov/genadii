"""Команда /heartbeat: управление самоинициацией бота в этом чате.

Просмотр доступен всем участникам; менять — админ (в личном чате владелец сам
себе админ по смыслу, поэтому там разрешаем любому участнику). Отключение
должно быть простым и очевидным — бот про него знает и подсказывает.
"""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import User, UserRole, Workspace, WorkspaceType
from app.services import audit, heartbeat, messages

router = Router(name="heartbeat")


def _can_change(user: User, workspace: Workspace) -> bool:
    # В личном чате владелец управляет своим ботом сам; в группе — только админ
    return user.role == UserRole.admin or workspace.type == WorkspaceType.personal


@router.message(Command("heartbeat"))
async def cmd_heartbeat(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    settings = get_settings()
    arg = (command.args or "").strip().lower()
    enabled = heartbeat.enabled_for(workspace)
    every = heartbeat.interval_minutes(workspace)

    if not arg:
        state = "включён ✅" if enabled else "выключен 🔕"
        text = (
            f"💓 <b>Хартбит этого чата: {state}</b>\n"
            f"Раз в ~{every // 60} ч я сам смотрю, не написать ли первым "
            "(напомнить о деле, вернуться к теме, спросить как дела) — но только "
            "если правда есть повод, и не по ночам.\n\n"
            "Выключить: <code>/heartbeat off</code>\n"
            "Включить: <code>/heartbeat on</code>\n"
            "Как часто: <code>/heartbeat 240</code> (минуты между проверками)"
        )
        sent = await message.answer(text)
        await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
        return

    if not _can_change(user, workspace):
        text = "Настраивать хартбит может только админ. 🙅"
        sent = await message.answer(text)
        await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
        return

    new_settings = dict(workspace.settings or {})
    if arg in ("on", "вкл", "1", "true"):
        new_settings["heartbeat"] = True
        text = "💓 Хартбит включён — иногда буду писать первым, если есть повод."
    elif arg in ("off", "выкл", "0", "false", "stop"):
        new_settings["heartbeat"] = False
        text = "🔕 Хартбит выключен — сам писать не буду, только когда позовёшь."
    elif arg.isdigit():
        value = max(30, min(1440, int(arg)))
        new_settings["heartbeat_interval"] = value
        new_settings.setdefault("heartbeat", True)
        text = (
            f"💓 Буду размышлять раз в ~{value} мин (писать — только при поводе). "
            "Выключить: <code>/heartbeat off</code>."
        )
    else:
        text = (
            "Формат: <code>/heartbeat on</code> / <code>/heartbeat off</code> / "
            "<code>/heartbeat 240</code> (минуты)."
        )
        sent = await message.answer(text)
        await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
        return

    workspace.settings = new_settings
    await audit.log(
        session,
        action="heartbeat_set",
        payload={"heartbeat": new_settings.get("heartbeat"),
                 "interval": new_settings.get("heartbeat_interval")},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
