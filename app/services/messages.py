from aiogram.types import (
    Message as TgMessage,
    MessageOrigin,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
)
from sqlalchemy import select
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


async def save_incoming(
    session: AsyncSession, workspace: Workspace, user: User, tg_message: TgMessage
) -> Message | None:
    content = tg_message.text or tg_message.caption
    if tg_message.photo:
        content = "[фото]" + (f" {content}" if content else "")
    if not content:
        return None

    label = forward_label(tg_message.forward_origin)
    if label:
        content = f"[переслано от {label}]\n{content}"

    return await save_user_text(
        session, workspace, user, content, tg_message_id=tg_message.message_id
    )


async def save_user_text(
    session: AsyncSession,
    workspace: Workspace,
    user: User,
    content: str,
    tg_message_id: int | None = None,
) -> Message:
    message = Message(
        workspace_id=workspace.id,
        user_id=user.id,
        tg_message_id=tg_message_id,
        role=MessageRole.user,
        content=content,
    )
    session.add(message)
    await session.flush()
    return message


async def update_edited(
    session: AsyncSession, workspace: Workspace, tg_message: TgMessage
) -> Message | None:
    """Правка сообщения пользователем — обновляет content в истории по tg_message_id."""
    content = tg_message.text or tg_message.caption
    if not content:
        return None
    label = forward_label(tg_message.forward_origin)
    if label:
        content = f"[переслано от {label}]\n{content}"

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
