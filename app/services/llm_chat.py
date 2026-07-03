import re
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

MAX_TOOL_ITERATIONS = 8  # исследовательские запросы могут делать много поисков подряд
ESCALATE_AFTER_ITERATIONS = 3  # если зациклились на инструментах — берём модель посильнее

# Некоторые модели при сбое function-calling вместо структурированного tool_calls
# пишут псевдо-вызов инструмента прямо в текст ответа (спецтокены вида <｜tool...｜>,
# [TOOL_CALLS], "invoke name="). Такое нельзя показывать пользователю как есть.
_FAKE_TOOL_CALL_RE = re.compile(
    r"<｜|<\|[^>]*(tool.call|tool.calls)[^>]*\|>|\[TOOL_CALLS\]|<invoke\s+name=",
    re.IGNORECASE,
)


def _has_leaked_tool_syntax(text: str) -> bool:
    return bool(text) and bool(_FAKE_TOOL_CALL_RE.search(text))


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

    query_text = extra_user_message if isinstance(extra_user_message, str) else None
    facts = await memory.list_facts(session, workspace, query_text=query_text)
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
    is_multimodal = isinstance(extra_user_message, list)
    model = pick_model(workspace, multimodal=is_multimodal)
    # Эскалация на smart-модель при зацикливании: не трогаем мультимодальные
    # ходы (там нужна именно vision-модель) и явный оверрайд пользователя.
    can_escalate = not is_multimodal and not (workspace.settings or {}).get(
        "model_override"
    )
    smart_model = get_settings().smart_model

    tool_schemas = [t.to_openrouter() for t in tools] or None
    ctx = ToolContext(
        session=session,
        workspace=workspace,
        user=user,
        bot=bot,
        chat_id=chat_id,
        target_message_id=target_message_id,
    )

    # Стриминг всегда, когда дан on_delta; мультимодальный ход тоже поддерживает stream.
    usages: list[client.LlmResult] = []
    for iteration in range(MAX_TOOL_ITERATIONS):
        # На последней итерации убираем инструменты: модель обязана дать финальный
        # ответ из уже собранного, а не звать очередной tool (иначе — фолбэк).
        last = iteration == MAX_TOOL_ITERATIONS - 1
        round_tools = None if last else tool_schemas
        round_model = (
            smart_model if can_escalate and iteration >= ESCALATE_AFTER_ITERATIONS else model
        )

        if on_delta is not None:
            result = await client.chat_stream(
                messages, round_model, tools=round_tools, on_delta=on_delta
            )
        else:
            result = await client.chat(messages, round_model, tools=round_tools)
        usages.append(result)

        if not result.tool_calls:
            if _has_leaked_tool_syntax(result.content):
                if not last:
                    # Модель хотела вызвать инструмент, но написала это текстом —
                    # не показываем сырой синтаксис, даём ей попробовать по-настоящему.
                    messages.append(result.raw_message)
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "[Системное: ты написал вызов инструмента текстом "
                                "вместо настоящего вызова. Не пиши синтаксис "
                                "инструментов в ответе — вызови инструмент по-"
                                "настоящему или ответь обычным текстом.]"
                            ),
                        }
                    )
                    continue
                return ChatOutcome(
                    text="Не получилось аккуратно завершить это через инструменты, попробуй ещё раз 🙈",
                    usages=usages,
                    attachments=ctx.attachments,
                )
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

    fallback_text = usages[-1].content or ""
    if not fallback_text or _has_leaked_tool_syntax(fallback_text):
        fallback_text = "Я запутался в инструментах, попробуй ещё раз 🙈"
    return ChatOutcome(text=fallback_text, usages=usages, attachments=ctx.attachments)


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
    user_id: int | None = None,
) -> None:
    for result in usages:
        session.add(
            LlmUsage(
                workspace_id=workspace.id,
                user_id=user_id,
                message_id=message_id,
                model=result.model,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                cost_usd=result.cost_usd,
                latency_ms=result.latency_ms,
            )
        )
    await session.flush()
