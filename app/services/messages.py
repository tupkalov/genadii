from datetime import datetime, timedelta

from aiogram.types import (
    Message as TgMessage,
    MessageOrigin,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
)
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, MessageRole, User, Workspace


def forward_label(origin: MessageOrigin | None) -> str | None:
    """Человекочитаемое «от кого переслано» из forward_origin."""
    if isinstance(origin, MessageOriginUser):
        sender = origin.sender_user
        name = sender.first_name or sender.username or str(sender.id)
        return f"{name} (@{sender.username})" if sender.username else name
    if isinstance(origin, MessageOriginHiddenUser):
        return origin.sender_user_name
    if isinstance(origin, MessageOriginChannel):
        return f"канал «{origin.chat.title}»"
    if isinstance(origin, MessageOriginChat):
        return f"чат «{origin.sender_chat.title}»"
    return None


REPLY_SNIPPET_LIMIT = 400


def _reply_author(reply: TgMessage) -> str:
    sender = reply.from_user
    if sender is not None:
        return sender.first_name or sender.username or str(sender.id)
    sender_chat = getattr(reply, "sender_chat", None)
    if sender_chat is not None and sender_chat.title:
        return f"«{sender_chat.title}»"
    return "кого-то"


def _decorate(tg_message: TgMessage, content: str) -> str:
    """Добавляет к тексту метки реплая, цитаты и пересылки, чтобы модель их учитывала."""
    # Реплай: без метки модель не знает, на какое сообщение отвечают, — а его
    # может вообще не быть в истории (другой бот, старое, не из whitelist'а)
    reply = tg_message.reply_to_message
    quote = getattr(tg_message, "quote", None)
    if reply is not None:
        # Цитата — выделенный фрагмент реплай-сообщения; если её нет, берём целиком
        quoted = (
            quote.text
            if quote and quote.text
            else (reply.text or reply.caption or ("[фото]" if reply.photo else None))
        )
        if quoted:
            snippet = quoted[:REPLY_SNIPPET_LIMIT] + (
                "…" if len(quoted) > REPLY_SNIPPET_LIMIT else ""
            )
            # Реплай на СОБСТВЕННОЕ сообщение бота — сильный сигнал: пользователь
            # продолжает/переспрашивает именно ту тему, даже если в чате только
            # что болтали про другое. Слабая модель иначе цепляется за недавнее
            # (реальный сбой: «Ещё раз давай» в ответ на ресёрч доставки → ответ
            # про постороннего человека из свежей истории). Директивная метка
            # держит якорь крепче пассивного «[в ответ на …]».
            reply_from = reply.from_user
            if reply_from is not None and reply_from.is_bot:
                content = (
                    "[Пользователь отвечает на ТВОЁ прошлое сообщение (ниже) — "
                    "он продолжает или переспрашивает именно эту тему. "
                    "Ориентируйся на неё, а не на то, что писали в чате перед этим.\n"
                    f"Твоё сообщение: «{snippet}»]\n{content}"
                )
            else:
                content = (
                    f"[в ответ на сообщение {_reply_author(reply)}: «{snippet}»]\n{content}"
                )
    elif quote and quote.text:
        content = f"[обращает внимание на цитату: «{quote.text}»]\n{content}"
    label = forward_label(tg_message.forward_origin)
    if label:
        content = f"[переслано от {label}]\n{content}"
    return content


async def save_incoming(
    session: AsyncSession, workspace: Workspace, user: User, tg_message: TgMessage
) -> Message | None:
    content = tg_message.text or tg_message.caption
    media_file_id = tg_message.photo[-1].file_id if tg_message.photo else None
    if tg_message.photo:
        content = "[фото]" + (f" {content}" if content else "")
    if not content:
        return None

    content = _decorate(tg_message, content)
    return await save_user_text(
        session,
        workspace,
        user,
        content,
        tg_message_id=tg_message.message_id,
        media_file_id=media_file_id,
    )


async def save_user_text(
    session: AsyncSession,
    workspace: Workspace,
    user: User,
    content: str,
    tg_message_id: int | None = None,
    media_file_id: str | None = None,
) -> Message:
    message = Message(
        workspace_id=workspace.id,
        user_id=user.id,
        tg_message_id=tg_message_id,
        role=MessageRole.user,
        content=content,
        media_file_id=media_file_id,
    )
    session.add(message)
    await session.flush()
    return message


# Окно «свежести» исторического фото: спрашивают «сколько на фотке» обычно про
# только что скинутую картинку, а не про снимок недельной давности.
RECENT_PHOTO_WINDOW = timedelta(minutes=30)


async def latest_photo_file_id(
    session: AsyncSession, workspace: Workspace
) -> str | None:
    """file_id последнего фото в чате, если оно свежее (см. RECENT_PHOTO_WINDOW).

    Нужно, когда о фото спрашивают позже и без реплая на него — тогда картинки
    в текущем ходе нет, но её можно перекачать из истории по сохранённому id.
    """
    row = await session.execute(
        select(Message.media_file_id, Message.created_at)
        .where(
            Message.workspace_id == workspace.id,
            Message.media_file_id.isnot(None),
        )
        .order_by(Message.id.desc())
        .limit(1)
    )
    result = row.first()
    if result is None:
        return None
    file_id, created_at = result
    if datetime.now(created_at.tzinfo) - created_at > RECENT_PHOTO_WINDOW:
        return None
    return file_id


async def update_edited(
    session: AsyncSession, workspace: Workspace, tg_message: TgMessage
) -> Message | None:
    """Правка сообщения пользователем — обновляет content в истории по tg_message_id."""
    content = tg_message.text or tg_message.caption
    if not content:
        return None
    content = _decorate(tg_message, content)

    message = await session.scalar(
        select(Message).where(
            Message.workspace_id == workspace.id,
            Message.tg_message_id == tg_message.message_id,
            Message.role == MessageRole.user,
        )
    )
    if message is None:
        return None
    message.content = content
    await session.flush()
    return message


def _summary_floor(workspace: Workspace) -> int:
    """Сообщения с id <= floor уже сжаты в сводку — их не трогаем при /undo."""
    return (workspace.settings or {}).get("summary_upto_id", 0)


async def drop_command_row(
    session: AsyncSession, workspace: Workspace, tg_message_id: int
) -> None:
    """Убирает из истории само командное сообщение (/undo, /retry, /search …),
    сохранённое middleware'ом — в контексте LLM ему делать нечего."""
    await session.execute(
        delete(Message).where(
            Message.workspace_id == workspace.id,
            Message.tg_message_id == tg_message_id,
            Message.role == MessageRole.user,
        )
    )


async def delete_last_exchange(session: AsyncSession, workspace: Workspace) -> int:
    """Для /undo: удаляет последний ответ ассистента и предшествующий ход юзера
    (вместе со всем, что между ними — вложения, многочастевые ответы).
    Возвращает число удалённых строк; 0 — нечего удалять."""
    floor = _summary_floor(workspace)
    last_assistant_id = await session.scalar(
        select(func.max(Message.id)).where(
            Message.workspace_id == workspace.id,
            Message.role == MessageRole.assistant,
            Message.id > floor,
        )
    )
    if last_assistant_id is None:
        return 0
    prev_user_id = await session.scalar(
        select(func.max(Message.id)).where(
            Message.workspace_id == workspace.id,
            Message.role == MessageRole.user,
            Message.id < last_assistant_id,
            Message.id > floor,
        )
    )
    start_id = prev_user_id if prev_user_id is not None else last_assistant_id
    result = await session.execute(
        delete(Message).where(
            Message.workspace_id == workspace.id, Message.id >= start_id
        )
    )
    return result.rowcount


async def delete_trailing_assistant(
    session: AsyncSession, workspace: Workspace
) -> int | None:
    """Для /retry: удаляет ответы ассистента после последнего хода юзера,
    чтобы история заканчивалась вопросом. Возвращает число удалённых строк
    (0 — юзер ещё не получил ответа, ретраить всё равно можно);
    None — ходов юзера в истории нет вообще."""
    floor = _summary_floor(workspace)
    last_user_id = await session.scalar(
        select(func.max(Message.id)).where(
            Message.workspace_id == workspace.id,
            Message.role == MessageRole.user,
            Message.id > floor,
        )
    )
    if last_user_id is None:
        return None
    result = await session.execute(
        delete(Message).where(
            Message.workspace_id == workspace.id, Message.id > last_user_id
        )
    )
    return result.rowcount


async def save_assistant(
    session: AsyncSession,
    workspace: Workspace,
    content: str,
    tg_message_id: int | None = None,
) -> Message:
    message = Message(
        workspace_id=workspace.id,
        user_id=None,
        tg_message_id=tg_message_id,
        role=MessageRole.assistant,
        content=content,
    )
    session.add(message)
    await session.flush()
    return message
