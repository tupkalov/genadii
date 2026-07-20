import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

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
from app.services import app_settings, guard, mcp, memory, skills as skills_service
from app.tools import permissions
from app.tools.executor import execute_tool_call
from app.tools.registry import ToolContext

logger = logging.getLogger("gennady.llm_chat")

MAX_TOOL_ITERATIONS = 8  # исследовательские запросы могут делать много поисков подряд

# Роутер моделей: дешёвая (default) модель ведёт простые ходы — болтовню, мнения,
# быстрые ответы из контекста. Как только ей нужен ИНСТРУМЕНТ (реальное действие
# с данными) или она сама решает, что задача требует размышления/решения (зовёт
# escalate), ход переигрывается умной моделью (smart_model). Так дешёвая никогда
# не исполняет инструменты сама — все реальные действия и решения на сильной
# модели (нет фантазий на action-задачах), а платим за неё только когда важно.
_ESCALATE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "escalate",
        "description": (
            "Передать ход более сильной модели. Зови, когда задача требует "
            "настоящего размышления, взвешенного решения или сложного выбора — "
            "а инструменты для неё не нужны. НЕ зови для простых ответов, шуток, "
            "болтовни и фактов, которые и так знаешь."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

# Некоторые модели при сбое function-calling вместо структурированного tool_calls
# пишут псевдо-вызов инструмента прямо в текст ответа (спецтокены вида <｜tool...｜>,
# [TOOL_CALLS], "invoke name="). Такое нельзя показывать пользователю как есть.
_FAKE_TOOL_CALL_RE = re.compile(
    r"<｜|<\|[^>]*(tool.call|tool.calls)[^>]*\|>|\[TOOL_CALLS\]|<invoke\s+name="
    # Вариант «function.RunPython / functions.run_python» отдельной строкой,
    # за которой модель пишет json-аргументы текстом (живой кейс DeepSeek)
    r"|^\s*functions?\.\w+\s*$"
    r"|<tool_call>",
    re.IGNORECASE | re.MULTILINE,
)


def _has_leaked_tool_syntax(text: str) -> bool:
    return bool(text) and bool(_FAKE_TOOL_CALL_RE.search(text))


@dataclass
class ChatOutcome:
    text: str
    usages: list[client.LlmResult]
    attachments: list[bytes]


def pick_model(
    workspace: Workspace, multimodal: bool = False, default_model: str | None = None
) -> str:
    """Дефолт (глобальный, БД или конфиг), override — в настройках workspace.

    default_model — эффективный глобальный дефолт (из app_settings.default_model);
    None → берём из конфига/.env. Для мультимодальных ходов (фото) — vision-модель:
    дефолтная модель картинки не понимает.
    """
    settings = get_settings()
    ws_settings = workspace.settings or {}
    if multimodal:
        return ws_settings.get("vision_model") or settings.vision_model
    return (
        ws_settings.get("model_override")
        or default_model
        or settings.default_model
    )


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


# Ниже этого разрыва между сообщениями считаем разговор непрерывным — маркер
# паузы не вставляем (обычная переписка, а не «вернулись через сутки»).
_GAP_THRESHOLD_MINUTES = 180


# Метку времени [ДД.ММ ЧЧ:ММ] мы ставим сообщениям в контексте; слабая модель
# иногда копирует её в начало ответа. Срезаем ведущие метки (промптом слабую
# модель не удержать).
_LEADING_TS_RE = re.compile(r"^\s*\[\d{2}\.\d{2}\s+\d{2}:\d{2}\]\s*")


def strip_leading_timestamp(text: str) -> str:
    prev = None
    while text and text != prev:
        prev = text
        text = _LEADING_TS_RE.sub("", text, count=1)
    return text


# Маркер «ответ дала умная модель» (эскалация на smart). Ставим в конец
# готового ответа; из истории срезаем, чтобы модель его не копировала.
SMART_MARK = "🧠"
_SMART_MARK_RE = re.compile(r"\s*🧠\s*$")


def mark_smart(text: str, escalated: bool) -> str:
    if escalated and text.strip() and not _SMART_MARK_RE.search(text):
        return f"{text} {SMART_MARK}"
    return text


def strip_smart_mark(text: str) -> str:
    return _SMART_MARK_RE.sub("", text)


def gap_note(delta_seconds: float) -> str | None:
    """Человеко-читаемый маркер паузы, если разрыв существенный, иначе None.

    Модель видит историю без времени — из-за этого вчерашний тред выглядит
    впритык к сегодняшнему ходу (реальный сбой: утренняя задача извинилась за
    «навыдумывал» вчера как за только что). Маркер возвращает чувство времени."""
    minutes = delta_seconds / 60
    if minutes < _GAP_THRESHOLD_MINUTES:
        return None
    hours = minutes / 60
    if hours >= 47:
        days = round(hours / 24)
        return f"[⏳ пауза в разговоре: прошло ~{days} дн]"
    return f"[⏳ пауза в разговоре: прошло ~{round(hours)} ч]"


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

    # Метка времени у каждого сообщения — абсолютная (стабильна → не ломает
    # промпт-кэш, в отличие от «N назад»). В том же поясе, что «Сейчас:» в
    # системном промпте, чтобы модель верно считала возраст темы.
    tz = ZoneInfo(settings.timezone)

    def _stamp(dt: datetime | None) -> str:
        return f"[{dt.astimezone(tz):%d.%m %H:%M}] " if dt is not None else ""

    messages: list[dict] = [{"role": "system", "content": system}]
    prev_dt: datetime | None = None
    for msg, author in await _load_history(session, workspace, settings.history_limit):
        # Маркер паузы между соседними сообщениями — громкий сигнал большого
        # разрыва (в дополнение к меткам времени), чтобы старая тема не читалась
        # как актуальная
        if prev_dt is not None and msg.created_at is not None:
            note = gap_note((msg.created_at - prev_dt).total_seconds())
            if note:
                messages.append({"role": "user", "content": note})
        prev_dt = msg.created_at
        if msg.role == MessageRole.assistant:
            # срезаем служебный 🧠-маркер, чтобы модель его не копировала
            body = strip_smart_mark(msg.content)
            messages.append(
                {"role": "assistant", "content": _stamp(msg.created_at) + body}
            )
        else:
            content = msg.content
            if workspace.type == WorkspaceType.group and author:
                content = f"{author}: {content}"
            messages.append(
                {"role": "user", "content": _stamp(msg.created_at) + content}
            )
    if extra_user_message:
        # Пауза между последним сообщением истории и текущим ходом (важно для
        # запланированных задач/хартбита, которые срабатывают спустя часы)
        if prev_dt is not None:
            note = gap_note((datetime.now(timezone.utc) - prev_dt).total_seconds())
            if note:
                messages.append({"role": "user", "content": note})
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
    force_model: str | None = None,
    allowed_tools: list[str] | None = None,
    guard_offtopic: bool = True,
) -> ChatOutcome:
    """Контекст + tool-calling цикл. Входящее сообщение уже в истории.

    extra_user_message-список (content-массив с image_url) включает
    мультимодальный режим — ход выполняет vision-модель.
    bot/chat_id/target_message_id пробрасываются в tools (реакции).
    force_model — разовый оверрайд модели (напр. /retry smart).
    allowed_tools — allowlist имён/масок для этого хода (скиллы): None — все.
    guard_offtopic — проверять финальный ответ на «не в тему» (см. services.guard);
    выключается для проактивных реплик (им не на что «отвечать по существу»).
    """
    tools = await permissions.enabled_tools(session, workspace)
    tools = tools + await mcp.workspace_mcp_tools(session, workspace)
    tools = skills_service.filter_tools(tools, allowed_tools)
    messages = await _build_messages(session, workspace, extra_user_message, tools, user)
    is_multimodal = isinstance(extra_user_message, list)
    # Резолвим оба тира: per-chat → глобальный (БД) → конфиг. Роутер работает,
    # когда workhorse ≠ smart. Мультимодалка идёт на vision-модель без роутинга;
    # force_model (напр. /retry smart) пиннит один ход на одну модель.
    ws_settings = workspace.settings or {}
    if is_multimodal:
        model = smart_model = pick_model(workspace, multimodal=True)
        can_escalate = False
    elif force_model:
        model = smart_model = force_model
        can_escalate = False
    else:
        # Легаси model_override пиннит ОБА тира (старое «одна модель, без роутера»)
        override = ws_settings.get("model_override")
        model = (
            ws_settings.get("workhorse")
            or override
            or await app_settings.workhorse_default(session)
        )
        smart_model = (
            ws_settings.get("smart")
            or override
            or await app_settings.smart_default(session)
        )
        can_escalate = model != smart_model

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
    # Черновик накапливает текст всех раундов: мысли предыдущего раунда не
    # затираются стримом следующего, а между раундами видно, какие инструменты
    # работают, — иначе сообщение «обрывается» и висит до финала.
    committed_text = ""
    round_delta = None
    if on_delta is not None:
        def round_delta(text: str) -> None:  # noqa: E306
            on_delta(f"{committed_text}{text}")

    # Первая линия (дешёвая модель) видит реальные инструменты + escalate, чтобы
    # уметь сказать «нужны действия / нужно подумать». Умная модель escalate не
    # видит — ей уже некуда эскалировать.
    first_line_schemas = tool_schemas
    if can_escalate:
        first_line_schemas = (tool_schemas or []) + [_ESCALATE_SCHEMA]

    usages: list[client.LlmResult] = []
    escalated = False  # sticky: как только перешли на smart — обратно не возвращаемся
    used_any_tool = False  # был ли хоть один вызов инструмента за ход
    deferral_nudged = False  # анти-«сделаю потом» наджем выдаём один раз
    for iteration in range(MAX_TOOL_ITERATIONS):
        # На последней итерации убираем инструменты: модель обязана дать финальный
        # ответ из уже собранного, а не звать очередной tool (иначе — фолбэк).
        last = iteration == MAX_TOOL_ITERATIONS - 1
        if last:
            round_tools = None
        elif escalated or not can_escalate:
            round_tools = tool_schemas
        else:
            round_tools = first_line_schemas
        round_model = smart_model if escalated else model

        try:
            if round_delta is not None:
                result = await client.chat_stream(
                    messages, round_model, tools=round_tools, on_delta=round_delta
                )
            else:
                result = await client.chat(messages, round_model, tools=round_tools)
        except client.LlmError:
            if round_model == model:
                raise
            # Эскалация — оптимизация, а не точка отказа: умная модель упала
            # (невалидный ID, недоступна) — доезжаем на базовой без эскалаций
            logger.warning(
                "Smart-модель %s упала, откатываюсь на %s", round_model, model
            )
            can_escalate = False
            escalated = False  # дальше едем на дешёвой, без повторных эскалаций
            round_tools = None if last else tool_schemas  # без escalate-схемы
            if round_delta is not None:
                result = await client.chat_stream(
                    messages, model, tools=round_tools, on_delta=round_delta
                )
            else:
                result = await client.chat(messages, model, tools=round_tools)
        usages.append(result)

        # РОУТЕР: дешёвая модель потянулась к инструменту (реальному или escalate)
        # — значит ход содержательный. Не исполняем её вызовы и не пишем их в
        # историю: переигрываем тот же ход умной моделью, она примет решения сама.
        if not escalated and can_escalate and result.tool_calls:
            escalated = True
            tool_names = ", ".join(
                tc.get("function", {}).get("name", "?") for tc in result.tool_calls
            )
            logger.info("Роутер: эскалация на %s (сигнал: %s)", smart_model, tool_names)
            if round_delta is not None:
                round_delta("🧠…")
            continue

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
            text = strip_leading_timestamp(result.content)
            # Guard: «сделаю потом» без единого инструмента — пустое обещание
            # (фоновой работы у бота нет). Даём ещё один tool-раунд с жёстким
            # наджем, чтобы модель выполнила запрос прямо сейчас. Один раз и
            # только если инструменты вообще были доступны и ещё есть раунды.
            if (
                not last
                and not used_any_tool
                and not deferral_nudged
                and tool_schemas
                and guard.is_deferral(text)
            ):
                deferral_nudged = True
                logger.info("Guard: ответ обещает работу «потом» без инструментов, перегенерирую")
                messages.append(result.raw_message)
                messages.append({"role": "user", "content": guard.NO_DEFER_NUDGE})
                continue
            # Guard: длинный ответ «не в тему» (модель ушла в чужой контекст) —
            # даём один шанс переписать строго по последнему сообщению. Проверка
            # fail-open: сбой/короткий ответ/мультимодалка нормальные реплики не трогают.
            if (
                guard_offtopic
                and get_settings().guard_offtopic
                and not is_multimodal
                and not ctx.attachments
            ):
                user_text = guard.last_user_text(messages)
                on_topic, check_usage = await guard.is_on_topic(
                    user_text, text, model
                )
                if check_usage is not None:
                    usages.append(check_usage)
                if not on_topic:
                    messages.append(result.raw_message)
                    messages.append({"role": "user", "content": guard.REWRITE_NUDGE})
                    retry = await client.chat(messages, model)
                    usages.append(retry)
                    if retry.content.strip() and not _has_leaked_tool_syntax(
                        retry.content
                    ):
                        text = strip_leading_timestamp(retry.content)
            return ChatOutcome(
                text=mark_smart(text, escalated),
                usages=usages, attachments=ctx.attachments,
            )

        # Раунд закончился вызовом инструментов: фиксируем его мысли в черновике
        # и показываем, что сейчас происходит, — иначе долгая пауза без движения
        if result.content.strip():
            committed_text += result.content.strip() + "\n\n"
        if round_delta is not None:
            tool_names = ", ".join(
                tc.get("function", {}).get("name", "?") for tc in result.tool_calls
            )
            round_delta(f"⚙️ {tool_names}…")

        messages.append(result.raw_message)
        used_any_tool = True
        tools_map = {t.name: t for t in tools}
        for tool_call in result.tool_calls:
            output = await execute_tool_call(ctx, tool_call, tools_map=tools_map)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", ""),
                    "content": output,
                }
            )

    fallback_text = strip_leading_timestamp(usages[-1].content or "")
    if not fallback_text or _has_leaked_tool_syntax(fallback_text):
        fallback_text = "Я запутался в инструментах, попробуй ещё раз 🙈"
    return ChatOutcome(
        text=mark_smart(fallback_text, escalated),
        usages=usages, attachments=ctx.attachments,
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
        guard_offtopic=False,  # проактивная реплика ни на что не «отвечает по теме»
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
