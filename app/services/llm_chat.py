from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import (
    LlmUsage,
    Message,
    MessageRole,
    User,
    UserRole,
    Workspace,
    WorkspaceType,
)
from app.llm import client
from app.llm.prompts import build_system_prompt
from app.services import memory
from app.tools import permissions
from app.tools.executor import execute_tool_call
from app.tools.registry import ToolContext

MAX_TOOL_ITERATIONS = 5


@dataclass
class ChatOutcome:
    text: str
    usages: list[client.LlmResult]
    attachments: list[bytes]


def pick_model(workspace: Workspace, multimodal: bool = False) -> str:
    """Дешёвый дефолт из конфига, override — в настройках workspace.

    Для мультимодальных ходов (фото в сообщении) — vision-модель:
    дефолтная модель картинки не понимает.
    """
    settings = get_settings()
    ws_settings = workspace.settings or {}
    if multimodal:
        return ws_settings.get("vision_model") or settings.vision_model
    return ws_settings.get("model_override") or settings.default_model


async def _load_history(
    session: AsyncSession, workspace: Workspace, limit: int
) -> list[tuple[Message, str | None]]:
    rows = (
        await session.execute(
            select(Message, User.first_name, User.username)
            .outerjoin(User, Message.user_id == User.id)
            .where(
                Message.workspace_id == workspace.id,
                Message.role.in_([MessageRole.user, MessageRole.assistant]),
            )
            .order_by(Message.id.desc())
            .limit(limit)
        )
    ).all()
    return [(m, first_name or username) for m, first_name, username in reversed(rows)]


async def _build_messages(
    session: AsyncSession,
    workspace: Workspace,
    extra_user_message: str | list[dict] | None = None,
    tools: list | None = None,
    user: User | None = None,
) -> list[dict]:
    settings = get_settings()
    system = build_system_prompt(workspace)

    if user is not None and user.role == UserRole.admin:
        from app.bot.handlers.admin import dashboard_hint

        system += (
            "\n\nСобеседник — админ. Если спросит про дашборд/веб-панель/статистику "
            "в браузере, дай эту инструкцию (перескажи своими словами, ссылку и "
            "SSH-команду сохрани точно):\n" + dashboard_hint()
        )

    if tools:
        system += (
            "\n\nТвои инструменты (вызывай их сам, когда уместно; на вопрос «что "
            "умеешь» перечисляй именно их):\n"
            + "\n".join(f"- {t.name}: {t.description.splitlines()[0]}" for t in tools)
        )

    summary = (workspace.settings or {}).get("history_summary")
    if summary:
        system += f"\n\nСводка более ранней части беседы:\n{summary}"

    facts = await memory.list_facts(session, workspace)
    if facts:
        system += "\n\nФакты из долгой памяти этого чата:\n" + "\n".join(
            f"- {f.content}" for f in facts
        )

    messages: list[dict] = [{"role": "system", "content": system}]
    for msg, author in await _load_history(session, workspace, settings.history_limit):
        if msg.role == MessageRole.assistant:
            messages.append({"role": "assistant", "content": msg.content})
        else:
            content = msg.content
            if workspace.type == WorkspaceType.group and author:
                content = f"{author}: {content}"
            messages.append({"role": "user", "content": content})
    if extra_user_message:
        messages.append({"role": "user", "content": extra_user_message})
    return messages


async def generate_reply(
    session: AsyncSession,
    workspace: Workspace,
    user: User,
    extra_user_message: str | list[dict] | None = None,
    bot: object | None = None,
    chat_id: int | None = None,
    target_message_id: int | None = None,
    on_delta=None,
) -> ChatOutcome:
    """Контекст + tool-calling цикл. Входящее сообщение уже в истории.

    extra_user_message-список (content-массив с image_url) включает
    мультимодальный режим — ход выполняет vision-модель.
    bot/chat_id/target_message_id пробрасываются в tools (реакции).
    """
    tools = await permissions.enabled_tools(session, workspace)
    messages = await _build_messages(session, workspace, extra_user_message, tools, user)
    model = pick_model(workspace, multimodal=isinstance(extra_user_message, list))

    tool_schemas = [t.to_openrouter() for t in tools] or None
    ctx = ToolContext(
        session=session,
        workspace=workspace,
        user=user,
        bot=bot,
        chat_id=chat_id,
        target_message_id=target_message_id,
    )

    # Стриминг только при отсутствии картинок в ответе неважен — стримим всегда,
    # когда дан on_delta; мультимодальный ход (vision) тоже поддерживает stream.
    usages: list[client.LlmResult] = []
    for _ in range(MAX_TOOL_ITERATIONS):
        if on_delta is not None:
            result = await client.chat_stream(
                messages, model, tools=tool_schemas, on_delta=on_delta
            )
        else:
            result = await client.chat(messages, model, tools=tool_schemas)
        usages.append(result)

        if not result.tool_calls:
            return ChatOutcome(
                text=result.content, usages=usages, attachments=ctx.attachments
            )

        messages.append(result.raw_message)
        for tool_call in result.tool_calls:
            output = await execute_tool_call(ctx, tool_call)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", ""),
                    "content": output,
                }
            )

    return ChatOutcome(
        text=usages[-1].content or "Я запутался в инструментах, попробуй ещё раз 🙈",
        usages=usages,
        attachments=ctx.attachments,
    )


INTERJECT_INSTRUCTION = (
    "[Системное: тебя НИКТО не звал. Это фоновая проверка — стоит ли вставить "
    "реплику в текущий разговор. Отвечай, ТОЛЬКО если тебе есть что добавить по "
    "-настоящему ценное, уместное и в твоём характере. Если добавить нечего — "
    "ответь ровно «SKIP» и ничего больше. Не здоровайся, не комментируй ради "
    "комментария.]"
)


async def maybe_interject(
    session: AsyncSession,
    workspace: Workspace,
    user: User,
    bot: object,
    chat_id: int,
) -> ChatOutcome | None:
    """Проактивная реплика: LLM сам решает, вставить что-то или смолчать (SKIP)."""
    outcome = await generate_reply(
        session, workspace, user,
        extra_user_message=INTERJECT_INSTRUCTION,
        bot=bot, chat_id=chat_id,
    )
    text = outcome.text.strip()
    if not text or (len(text) < 12 and "SKIP" in text.upper()):
        return None
    return outcome


async def log_usages(
    session: AsyncSession,
    workspace: Workspace,
    usages: list[client.LlmResult],
    message_id: int | None = None,
) -> None:
    for result in usages:
        session.add(
            LlmUsage(
                workspace_id=workspace.id,
                message_id=message_id,
                model=result.model,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                cost_usd=result.cost_usd,
                latency_ms=result.latency_ms,
            )
        )
    await session.flush()
