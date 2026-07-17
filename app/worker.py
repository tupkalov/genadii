import logging
import random
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import BufferedInputFile
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatting import send_rendered
from app.config import get_settings
from app.db.models import ScheduledTask, User, Workspace
from app.db.session import session_factory
from app.llm import http as llm_http
from app.llm.client import LlmError
from app.services import (
    alerts,
    audit,
    budget,
    heartbeat,
    llm_chat,
    messages,
    reminders,
    skills,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gennady.worker")

TG_LIMIT = 4000


async def startup(ctx: dict) -> None:
    ctx["bot"] = Bot(token=get_settings().bot_token)

    # Рестарт мог прервать выполнение — возвращаем зависшие 'running' в очередь.
    # Worker один, поэтому сброс на старте безопасен; повторный запуск задачи допустим.
    async with session_factory() as session:
        result = await session.execute(
            update(ScheduledTask)
            .where(ScheduledTask.status == "running")
            .values(status="pending")
        )
        await session.commit()
    if result.rowcount:
        logger.warning("Сброшено зависших running-задач: %s", result.rowcount)

    logger.info("Worker Геннадия запущен")


async def shutdown(ctx: dict) -> None:
    await ctx["bot"].session.close()
    await llm_http.aclose()


async def _send_and_log(
    bot: Bot, session: AsyncSession, workspace: Workspace, text: str
) -> None:
    if len(text) > TG_LIMIT:
        text = text[:TG_LIMIT] + "…"
    sent = await bot.send_message(workspace.tg_chat_id, text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)


async def _run_reminder(
    bot: Bot, session: AsyncSession, task: ScheduledTask, workspace: Workspace
) -> None:
    payload = task.payload or {}
    name = payload.get("user_name")
    text = f"⏰ {name + ', н' if name else 'Н'}апоминание: {payload.get('text', '…')}"
    await _send_and_log(bot, session, workspace, text)


async def _run_agent_task(
    bot: Bot, session: AsyncSession, task: ScheduledTask, workspace: Workspace
) -> None:
    """Пробуждение: LLM-ход с инструментами по сохранённой инструкции."""
    over, spend, limit = await budget.check(session, workspace)
    if over:
        await _send_and_log(
            bot,
            session,
            workspace,
            f"⛔ Задача #{task.id} пропущена: месячный бюджет чата исчерпан "
            f"(${spend:.2f} из ${limit:.2f}).",
        )
        return

    payload = task.payload or {}
    user = await session.get(User, task.user_id)

    allowed_tools = None
    if payload.get("skill_id"):
        # Задача-скилл: инструкция и allowlist берутся из скилла в момент
        # выполнения — правки скилла подхватываются без пересоздания задач
        from app.db.models import Skill

        skill = await session.get(Skill, payload["skill_id"])
        if skill is None or not skill.enabled:
            await _send_and_log(
                bot, session, workspace,
                f"⚠️ Задача #{task.id}: скилл удалён или выключен — пропускаю.",
            )
            return
        body = skills.build_prompt(skill, payload.get("event"))
        allowed_tools = skill.allowed_tools
    else:
        body = payload.get("text", "")

    instruction = (
        f"[Запланированная задача #{task.id}, поставил(а) "
        f"{payload.get('user_name') or 'кто-то из чата'}. Выполни и напиши результат "
        "в чат. Ты работаешь без присмотра: если инструмент падает — почини и "
        "перезапусти прямо сейчас; данные только из результатов инструментов, "
        "ничего не выдумывай; не обещай доделать позже.]\n"
        f"{body}"
    )
    outcome = await llm_chat.generate_reply(
        session, workspace, user, extra_user_message=instruction,
        allowed_tools=allowed_tools,
    )
    text = outcome.text.strip() or "…"
    sent = await send_rendered(bot, workspace.tg_chat_id, text)
    saved = await messages.save_assistant(
        session, workspace, text, tg_message_id=sent.message_id
    )
    await llm_chat.log_usages(
        session, workspace, outcome.usages, message_id=saved.id, user_id=task.user_id
    )

    for image in outcome.attachments[:2]:
        photo_msg = await bot.send_photo(
            workspace.tg_chat_id, BufferedInputFile(image, filename="gennady.png")
        )
        await messages.save_assistant(
            session, workspace, "[картинка]", tg_message_id=photo_msg.message_id
        )


async def claim_task(session: AsyncSession, task_id: int) -> bool:
    """Атомарный захват задачи: True, если именно мы перевели pending→running.

    Свипы могут перекрываться (LLM-задача живёт дольше 20с между кронами),
    поэтому смена статуса через ORM-присваивание недостаточна — нужен
    UPDATE ... WHERE status='pending' с проверкой rowcount."""
    claimed = await session.execute(
        update(ScheduledTask)
        .where(ScheduledTask.id == task_id, ScheduledTask.status == "pending")
        .values(status="running")
    )
    await session.commit()
    return claimed.rowcount == 1


async def check_due_tasks(ctx: dict) -> None:
    """Sweeper: выполняет просроченные pending-задачи. Источник правды — БД."""
    bot: Bot = ctx["bot"]
    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(ScheduledTask, Workspace)
                .join(Workspace, ScheduledTask.workspace_id == Workspace.id)
                .where(
                    ScheduledTask.status == "pending",
                    ScheduledTask.run_at <= now,
                )
                .order_by(ScheduledTask.run_at)
                .limit(20)
            )
        ).all()

        for task, workspace in rows:
            if not await claim_task(session, task.id):
                continue  # параллельный свип уже забрал эту задачу
            # Синхронизируем ORM-объект с БД: иначе для cron-задачи финальное
            # task.status = "pending" выглядело бы как no-op и не записалось бы
            task.status = "running"

            try:
                if task.kind == "agent_task":
                    await _run_agent_task(bot, session, task, workspace)
                else:
                    await _run_reminder(bot, session, task, workspace)

                if task.cron:  # повторяющаяся — планируем следующий запуск
                    task.run_at = reminders.next_run_from_cron(task.cron)
                    task.status = "pending"
                else:
                    task.status = "done"
                logger.info("Задача #%s (%s) выполнена", task.id, task.kind)
            except Exception as exc:
                logger.exception("Задача #%s упала", task.id)
                task.status = "failed"
                if isinstance(exc, LlmError):
                    await alerts.record_llm_failure(bot)
                try:
                    await _send_and_log(
                        bot,
                        session,
                        workspace,
                        f"⚠️ Задача #{task.id} не выполнилась: "
                        f"{alerts.safe_error_text(exc)}",
                    )
                except Exception:
                    logger.exception("Не смог сообщить об ошибке задачи #%s", task.id)

            await session.commit()


async def reindex_memory(ctx: dict) -> None:
    """Доиндексация фактов, сохранённых без embedding (сбой/отсутствие API)."""
    from app.db.models import MemoryEntry
    from app.llm import embeddings

    if not embeddings.available():
        return

    try:
        async with session_factory() as session:
            entries = (
                (
                    await session.execute(
                        select(MemoryEntry)
                        .where(
                            MemoryEntry.embedding.is_(None),
                            MemoryEntry.archived_at.is_(None),
                        )
                        .limit(20)
                    )
                )
                .scalars()
                .all()
            )
            indexed = 0
            for entry in entries:
                try:
                    entry.embedding = await embeddings.embed(entry.content)
                    indexed += 1
                except Exception as exc:  # noqa: BLE001 — API лежит, попробуем в следующий раз
                    logger.warning("Доиндексация факта #%s не удалась: %s", entry.id, exc)
                    break
            await session.commit()
        if indexed:
            logger.info("Доиндексировано фактов: %s", indexed)
    except Exception as exc:
        logger.exception("Cron reindex_memory упал целиком")
        await alerts.notify_admins(
            ctx["bot"], f"⚠️ Cron reindex_memory упал: {exc}", kind="cron:reindex_memory"
        )


async def send_digests(ctx: dict) -> None:
    """Раз в минуту: рассылает дайджест пользователям, у кого настал их час."""
    from zoneinfo import ZoneInfo

    from app.db.models import User, WorkspaceType
    from app.services import digest

    bot: Bot = ctx["bot"]
    now = datetime.now(ZoneInfo(get_settings().timezone))
    hhmm = now.strftime("%H:%M")
    today = now.date().isoformat()

    try:
        async with session_factory() as session:
            personals = (
                await session.scalars(
                    select(Workspace).where(Workspace.type == WorkspaceType.personal)
                )
            ).all()
            for ws in personals:
                settings = ws.settings or {}
                if (
                    settings.get("digest_time") != hhmm
                    or settings.get("digest_last_date") == today
                ):
                    continue
                user = await session.scalar(
                    select(User).where(User.tg_id == ws.tg_chat_id)
                )
                if user is None:
                    continue
                try:
                    text = await digest.build_for_user(session, user)
                    if text:
                        await send_rendered(bot, ws.tg_chat_id, text)
                    ws.settings = {**settings, "digest_last_date": today}
                    await session.commit()
                    logger.info("Дайджест отправлен пользователю %s", ws.tg_chat_id)
                except Exception:
                    logger.exception("Дайджест для %s упал", ws.tg_chat_id)
                    await session.rollback()
    except Exception as exc:
        logger.exception("Cron send_digests упал целиком")
        await alerts.notify_admins(
            bot, f"⚠️ Cron send_digests упал: {exc}", kind="cron:send_digests"
        )


async def compress_histories(ctx: dict) -> None:
    """Ежечасное сжатие старой истории длинных чатов в сводку."""
    from app.services import summaries

    try:
        async with session_factory() as session:
            workspaces = (await session.scalars(select(Workspace))).all()
            for workspace in workspaces:
                try:
                    if await summaries.compress_workspace(session, workspace):
                        await session.commit()
                except Exception:
                    logger.exception("Сжатие истории workspace %s упало", workspace.id)
                    await session.rollback()
    except Exception as exc:
        logger.exception("Cron compress_histories упал целиком")
        await alerts.notify_admins(
            ctx["bot"], f"⚠️ Cron compress_histories упал: {exc}", kind="cron:compress_histories"
        )


async def _run_one_heartbeat(
    bot: Bot, session: AsyncSession, workspace: Workspace, now: datetime, percent: int
) -> None:
    """Один хартбит-ход для воркспейса: рефлексия → отправка (или молчание).

    heartbeat_last обновляем ВСЕГДА (и когда смолчали), чтобы разнести
    LLM-ходы во времени; иначе следующий крон снова дёрнет модель."""
    user = await heartbeat._pick_user(session, workspace)
    if user is None:
        return
    tasks_note = await heartbeat._upcoming_tasks_note(session, workspace)
    instruction = heartbeat.build_instruction(tasks_note, percent)

    outcome = await llm_chat.generate_reply(
        session, workspace, user,
        extra_user_message=instruction,
        bot=bot, chat_id=workspace.tg_chat_id,
        guard_offtopic=False,  # хартбит ни на что не «отвечает по теме»
    )
    workspace.settings = {**(workspace.settings or {}), "heartbeat_last": now.isoformat()}

    text = outcome.text.strip()
    spoke = not heartbeat.is_silence(text)

    message_id = None
    if spoke:
        sent = await send_rendered(bot, workspace.tg_chat_id, text)
        saved = await messages.save_assistant(
            session, workspace, text, tg_message_id=sent.message_id
        )
        message_id = saved.id

    # Расход рефлексии учитываем ВСЕГДА — в т.ч. когда смолчал (иначе тихие
    # размышления жгли бы токены мимо биллинга и бюджета).
    await llm_chat.log_usages(
        session, workspace, outcome.usages, message_id=message_id, user_id=user.id
    )
    # Персистентный след в audit_log: видно, когда хартбит думал и заговорил ли
    await audit.log(
        session,
        action="heartbeat",
        payload={"spoke": spoke, "initiative": percent},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    logger.info(
        "Хартбит ws %s: %s", workspace.id, "написал первым" if spoke else "молчу"
    )


async def run_heartbeats(ctx: dict) -> None:
    """Периодически будим бота на тихие чаты — сам решает, писать ли первым."""
    bot: Bot = ctx["bot"]
    now = datetime.now(timezone.utc)
    try:
        async with session_factory() as session:
            workspaces = (await session.scalars(select(Workspace))).all()
            for workspace in workspaces:
                try:
                    if not await heartbeat.should_run(session, workspace, now):
                        continue
                    # «Тик» состоялся: пульс задаёт частоту размышлений, а
                    # initiative % — вероятность, что этот тик станет сообщением.
                    # Бросок ДО LLM: при низкой инициативе почти всегда экономим
                    # ход, но heartbeat_last всё равно двигаем (ритм = интервал).
                    percent = heartbeat.initiative_percent(workspace)
                    if random.random() * 100 < percent:
                        await _run_one_heartbeat(bot, session, workspace, now, percent)
                    else:
                        workspace.settings = {
                            **(workspace.settings or {}),
                            "heartbeat_last": now.isoformat(),
                        }
                    await session.commit()
                except LlmError as exc:
                    logger.warning("Хартбит ws %s: LLM упал: %s", workspace.id, exc)
                    await alerts.record_llm_failure(bot)
                    await session.rollback()
                except Exception:
                    logger.exception("Хартбит ws %s упал", workspace.id)
                    await session.rollback()
    except Exception as exc:
        logger.exception("Cron run_heartbeats упал целиком")
        await alerts.notify_admins(
            ctx["bot"], f"⚠️ Cron run_heartbeats упал: {exc}", kind="cron:run_heartbeats"
        )


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    on_startup = startup
    on_shutdown = shutdown
    health_check_interval = 60  # для healthcheck'а `arq --check` в compose
    cron_jobs = [
        # max_tries=1: arq не должен перезапускать полусделанный свип по
        # таймауту — задачи и так подберёт следующий крон через 20с
        cron(check_due_tasks, second={0, 20, 40}, run_at_startup=True, timeout=600, max_tries=1),
        cron(reindex_memory, minute={0, 15, 30, 45}, run_at_startup=True),
        cron(compress_histories, minute={5}, run_at_startup=True),
        cron(send_digests, second={0}),  # ежеминутная проверка времени дайджестов
        # Хартбит: проверяем гейты каждые ~15 мин, LLM-ход — только для «дозревших»
        # чатов (интервал размышления ≥ heartbeat_interval_minutes)
        cron(run_heartbeats, minute={8, 23, 38, 53}),
    ]
