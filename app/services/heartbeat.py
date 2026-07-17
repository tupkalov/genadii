"""Хартбит: субъектность бота — сам по таймеру решает, не написать ли первым.

В отличие от проактивности (`llm_chat.maybe_interject`), которая реагирует на
чужое входящее сообщение, хартбит триггерится по таймеру из воркера: бот
«просыпается» на тихий чат, оглядывается (недавняя история и память уже в
контексте, ближайшие задачи подаём отдельно) и решает — есть ли сейчас
настоящий повод написать. Уклон сильно в молчание: в большинстве проверок
модель возвращает сентинел «МОЛЧУ», и мы ничего не отправляем.

Гейты дешёвые (без LLM) и отсекают почти все проверки заранее:
- выключен в этом чате / не настал интервал размышления;
- тихие часы (по settings.timezone);
- чат «живой» — недавнее сообщение или бот прямо сейчас общается;
- исчерпан бюджет.
LLM-ход происходит только когда все гейты пройдены.
"""
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Message, ScheduledTask, User, Workspace
from app.services import budget as budget_service

logger = logging.getLogger("gennady.heartbeat")

# Сентинел «мне нечего сказать»: модель возвращает его, когда повода нет.
SILENCE_TOKENS = ("МОЛЧУ", "SILENCE")

_INSTRUCTION_HEAD = (
    "[Системное: тебя НИКТО не звал и никто только что не писал. Ты сам "
    "проснулся и смотришь на этот чат со стороны: стоит ли написать первым "
    "прямо сейчас?\n\n"
    "Ты синхронный — пиши только то, что можешь сказать в этом же ходе (нужен "
    "факт — сходи инструментом сейчас, не обещай «потом»).\n\n"
    "Уместные поводы:\n"
    "- приближается или просрочено дело/напоминание — мягко напомнить;\n"
    "- недавно оборвалась тема или кто-то обещал что-то сделать — вернуться к "
    "ней, спросить, как вышло;\n"
    "- в памяти есть повод (планы, событие, «спросить как прошло»);\n"
    "- очень редко и аккуратно — просто дружеский чек-ин или любопытство.\n\n"
    "ГЛАВНОЕ: по умолчанию повода НЕТ. Пиши, только если это правда уместно, "
    "к месту по времени и не выглядит как спам или дежурная болтовня. Не "
    "повторяй то, что уже недавно говорил. Если сомневаешься — молчи.\n\n"
    "Если писать не стоит — ответь РОВНО одним словом: МОЛЧУ (и ничего больше).\n"
    "Если стоит — напиши одно короткое живое сообщение в своём характере, без "
    "приветствий-заглушек и без пояснений, что это «фоновая проверка».]"
)


def is_quiet_hours(now_local: datetime, start_hour: int, end_hour: int) -> bool:
    """Тихие часы по локальному времени. Интервал может пересекать полночь
    (напр. 22→9): тогда «тихо» — это hour>=start ИЛИ hour<end."""
    hour = now_local.hour
    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def enabled_for(workspace: Workspace) -> bool:
    settings = get_settings()
    return bool(
        (workspace.settings or {}).get("heartbeat", settings.heartbeat_default_on)
    )


def _get_dt(workspace: Workspace, key: str) -> datetime | None:
    raw = (workspace.settings or {}).get(key)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def interval_minutes(workspace: Workspace) -> int:
    override = (workspace.settings or {}).get("heartbeat_interval")
    if isinstance(override, int) and override > 0:
        return override
    return get_settings().heartbeat_interval_minutes


def due_to_reflect(workspace: Workspace, now_utc: datetime) -> bool:
    """Настал ли интервал размышления (разносит LLM-ходы во времени)."""
    last = _get_dt(workspace, "heartbeat_last")
    if last is None:
        return True
    return now_utc - last >= timedelta(minutes=interval_minutes(workspace))


async def _last_message_at(session: AsyncSession, workspace: Workspace) -> datetime | None:
    return await session.scalar(
        select(Message.created_at)
        .where(Message.workspace_id == workspace.id)
        .order_by(Message.id.desc())
        .limit(1)
    )


async def _pick_user(session: AsyncSession, workspace: Workspace) -> User | None:
    """Кого считать «собеседником» для рефлексии: последний писавший, иначе
    любой участник (нужен для персоны/роли в generate_reply)."""
    user_id = await session.scalar(
        select(Message.user_id)
        .where(Message.workspace_id == workspace.id, Message.user_id.isnot(None))
        .order_by(Message.id.desc())
        .limit(1)
    )
    if user_id is not None:
        user = await session.get(User, user_id)
        if user is not None:
            return user
    return await session.scalar(select(User).limit(1))


async def _upcoming_tasks_note(session: AsyncSession, workspace: Workspace) -> str:
    """Ближайшие/просроченные задачи чата — материал для повода (в контекст
    истории они не попадают, поэтому подаём отдельно)."""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=36)
    rows = (
        await session.execute(
            select(ScheduledTask)
            .where(
                ScheduledTask.workspace_id == workspace.id,
                ScheduledTask.status == "pending",
                ScheduledTask.run_at.isnot(None),
                ScheduledTask.run_at <= horizon,
            )
            .order_by(ScheduledTask.run_at)
            .limit(5)
        )
    ).scalars().all()
    if not rows:
        return ""
    tz = ZoneInfo(get_settings().timezone)
    lines = []
    for task in rows:
        when = task.run_at.astimezone(tz).strftime("%d.%m %H:%M")
        what = (task.payload or {}).get("text", task.kind)
        overdue = " (просрочено)" if task.run_at < now else ""
        lines.append(f"- {when}{overdue}: {what}")
    return "Ближайшие задачи/напоминания этого чата:\n" + "\n".join(lines)


def build_instruction(tasks_note: str) -> str:
    if tasks_note:
        return f"{_INSTRUCTION_HEAD}\n\n{tasks_note}"
    return _INSTRUCTION_HEAD


def is_silence(text: str) -> bool:
    """Модель решила смолчать? Короткий ответ с сентинелом = молчание."""
    stripped = (text or "").strip()
    if not stripped:
        return True
    upper = stripped.upper()
    # Сентинел засчитываем, только если ответ короткий — иначе живое сообщение,
    # где слово «молчу» встретилось случайно, не глушим.
    return len(stripped) < 20 and any(tok in upper for tok in SILENCE_TOKENS)


async def should_run(
    session: AsyncSession, workspace: Workspace, now_utc: datetime
) -> bool:
    """Все дешёвые гейты перед дорогим LLM-ходом. True → можно размышлять."""
    settings = get_settings()
    if not enabled_for(workspace):
        return False
    if not due_to_reflect(workspace, now_utc):
        return False
    now_local = now_utc.astimezone(ZoneInfo(settings.timezone))
    if is_quiet_hours(
        now_local, settings.heartbeat_quiet_start_hour, settings.heartbeat_quiet_end_hour
    ):
        return False
    # Чат «живой» — не встреваем в идущий разговор
    last_msg = await _last_message_at(session, workspace)
    if last_msg is not None:
        if last_msg.tzinfo is None:
            last_msg = last_msg.replace(tzinfo=timezone.utc)
        if now_utc - last_msg < timedelta(minutes=settings.heartbeat_min_silence_minutes):
            return False
    else:
        return False  # пустой чат — не о чем инициировать
    over, _spend, _limit = await budget_service.check(session, workspace)
    if over:
        return False
    return True
