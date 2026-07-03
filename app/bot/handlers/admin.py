from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, MessageOriginHiddenUser, MessageOriginUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserRole, Workspace
from app.services import audit, messages, users

router = Router(name="admin")

NOT_ADMIN = "Эта команда только для админа. 🙅"


def _target_tg(
    message: Message, command: CommandObject
) -> tuple[int | None, str | None, str | None]:
    """(tg_id, username, error): цель из reply (в т.ч. пересланного сообщения)
    или из аргумента-числа."""
    reply = message.reply_to_message
    if reply:
        # Reply на пересланное сообщение: нужен автор оригинала, не пересылавший
        origin = reply.forward_origin
        if isinstance(origin, MessageOriginUser):
            return origin.sender_user.id, origin.sender_user.username, None
        if isinstance(origin, MessageOriginHiddenUser):
            return None, None, (
                f"У «{origin.sender_user_name}» аккаунт скрыт при пересылке — "
                "Telegram не отдаёт его ID. Пусть напишет мне сам или пришли ID числом."
            )
        if reply.from_user and not reply.from_user.is_bot:
            return reply.from_user.id, reply.from_user.username, None
    arg = (command.args or "").strip()
    if arg.isdigit():
        return int(arg), None, None
    return None, None, None


async def _reply(message: Message, session: AsyncSession, workspace: Workspace, text: str):
    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)


@router.message(Command("invite"))
async def cmd_invite(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    if user.role != UserRole.admin:
        return await _reply(message, session, workspace, NOT_ADMIN)

    tg_id, username, error = _target_tg(message, command)
    if error:
        return await _reply(message, session, workspace, error)
    if tg_id is None:
        return await _reply(
            message,
            session,
            workspace,
            "Кого приглашаем? <code>/invite tg_id</code>, ответь командой на "
            "сообщение человека в группе — или на пересланное от него сообщение.\n"
            "Свой ID человек может узнать у @userinfobot.",
        )

    target = await users.get_by_tg_id(session, tg_id)
    if target is None:
        target = User(tg_id=tg_id, username=username, invited_by_id=user.id)
        session.add(target)
        await session.flush()
        text = f"Добавил <code>{tg_id}</code> в whitelist. Добро пожаловать! 🎉"
    elif not target.is_active:
        target.is_active = True
        text = f"Вернул <code>{tg_id}</code> в строй. 🎉"
    else:
        text = f"<code>{tg_id}</code> и так в whitelist."

    await audit.log(
        session,
        action="user_invited",
        payload={"tg_id": tg_id},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    await _reply(message, session, workspace, text)


@router.message(Command("kick"))
async def cmd_kick(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    if user.role != UserRole.admin:
        return await _reply(message, session, workspace, NOT_ADMIN)

    tg_id, _, error = _target_tg(message, command)
    if error:
        return await _reply(message, session, workspace, error)
    target = await users.get_by_tg_id(session, tg_id) if tg_id else None
    if target is None or not target.is_active:
        text = "Кого выгоняем? <code>/kick tg_id</code> или reply. Активного такого нет."
    elif target.role == UserRole.admin:
        text = "Админа выгнать нельзя. 😤"
    else:
        target.is_active = False
        await audit.log(
            session,
            action="user_kicked",
            payload={"tg_id": tg_id},
            workspace_id=workspace.id,
            user_id=user.id,
        )
        text = f"<code>{tg_id}</code> больше не в whitelist."
    await _reply(message, session, workspace, text)


def dashboard_hint() -> str:
    from app.config import get_settings

    host = get_settings().server_host or "<твой-сервер>"
    return (
        "🖥 <b>Веб-дашборд</b> (расходы, память, задачи, аудит)\n"
        "Крутится на сервере по адресу <code>http://localhost:8000/</code> "
        "(наружу не смотрит — только localhost).\n\n"
        "Открыть со своей машины через SSH-туннель:\n"
        f"<code>ssh -L 8000:localhost:8000 {host}</code>\n"
        "затем в браузере — <code>http://localhost:8000/</code>"
    )


@router.message(Command("dashboard"))
async def cmd_dashboard(
    message: Message, user: User, workspace: Workspace, session: AsyncSession
) -> None:
    if user.role != UserRole.admin:
        return await _reply(message, session, workspace, NOT_ADMIN)
    await _reply(message, session, workspace, dashboard_hint())


@router.message(Command("users"))
async def cmd_users(
    message: Message, user: User, workspace: Workspace, session: AsyncSession
) -> None:
    if user.role != UserRole.admin:
        return await _reply(message, session, workspace, NOT_ADMIN)

    everyone = (await session.execute(select(User).order_by(User.id))).scalars()
    lines = [
        f"{'👑' if u.role == UserRole.admin else '👤'}"
        f"{'' if u.is_active else '🚫'} "
        f"<code>{u.tg_id}</code> @{u.username or '—'} ({u.first_name or '—'})"
        for u in everyone
    ]
    await _reply(message, session, workspace, "<b>Пользователи:</b>\n" + "\n".join(lines))
