import html

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message as DbMessage
from app.db.models import MessageRole, User, Workspace
from app.services import memory, messages, reminders

router = Router(name="search")

MESSAGE_LIMIT = 10
SNIPPET_LEN = 120


def _like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.message(Command("search"))
async def cmd_search(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    """Поиск по памяти (семантический) и истории сообщений (подстрока) этого чата."""
    query = (command.args or "").strip()
    # Команда уже сохранена в историю middleware'ом и содержит сам запрос —
    # убираем, чтобы не находить её же и не мусорить контекст LLM
    await messages.drop_command_row(session, workspace, message.message_id)
    if not query:
        await message.answer("Формат: <code>/search что ищем</code>")
        return

    facts = await memory.search(session, workspace, query, limit=5)
    history = (
        await session.scalars(
            select(DbMessage)
            .where(
                DbMessage.workspace_id == workspace.id,
                DbMessage.role.in_([MessageRole.user, MessageRole.assistant]),
                DbMessage.content.ilike(_like_pattern(query), escape="\\"),
            )
            .order_by(DbMessage.id.desc())
            .limit(MESSAGE_LIMIT)
        )
    ).all()

    parts = []
    if facts:
        parts.append("<b>Из памяти:</b>")
        parts += [f"• {html.escape(f.content)}" for f in facts]
    if history:
        if parts:
            parts.append("")
        parts.append("<b>Из переписки:</b>")
        for m in history:
            snippet = m.content[:SNIPPET_LEN] + ("…" if len(m.content) > SNIPPET_LEN else "")
            who = "🤖" if m.role == MessageRole.assistant else "👤"
            parts.append(
                f"• {who} {reminders.format_local(m.created_at)}: {html.escape(snippet)}"
            )
    text = "\n".join(parts) or f"По запросу «{html.escape(query)}» ничего не нашёл. 🤷"

    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
