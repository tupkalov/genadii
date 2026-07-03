from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import ScheduledTask, User, Workspace


def local_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def parse_local(value: str) -> datetime:
    """ISO-строка (локальное время чата) -> aware UTC datetime."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=local_tz())
    return dt.astimezone(timezone.utc)


def format_local(dt: datetime) -> str:
    return dt.astimezone(local_tz()).strftime("%Y-%m-%d %H:%M")


def next_run_from_cron(cron_expr: str) -> datetime:
    """Следующий запуск по cron-выражению (в локальной таймзоне) -> UTC."""
    base = datetime.now(local_tz())
    return croniter(cron_expr, base).get_next(datetime).astimezone(timezone.utc)


def validate_cron(cron_expr: str) -> bool:
    try:
        croniter(cron_expr)
        return True
    except (ValueError, KeyError):
        return False


async def create(
    session: AsyncSession,
    workspace: Workspace,
    user: User,
    text: str,
    run_at_utc: datetime,
    kind: str = "reminder",
    cron_expr: str | None = None,
) -> ScheduledTask:
    task = ScheduledTask(
        workspace_id=workspace.id,
        user_id=user.id,
        kind=kind,
        payload={"text": text, "user_name": user.first_name or user.username},
        run_at=run_at_utc,
        cron=cron_expr,
        status="pending",
    )
    session.add(task)
    await session.flush()
    return task


async def list_pending(
    session: AsyncSession, workspace: Workspace
) -> list[ScheduledTask]:
    return list(
        (
            await session.execute(
                select(ScheduledTask)
                .where(
                    ScheduledTask.workspace_id == workspace.id,
                    ScheduledTask.status == "pending",
                )
                .order_by(ScheduledTask.run_at)
            )
        )
        .scalars()
        .all()
    )


async def cancel(
    session: AsyncSession, workspace: Workspace, task_id: int
) -> ScheduledTask | None:
    task = await session.get(ScheduledTask, task_id)
    if (
        task is None
        or task.workspace_id != workspace.id
        or task.status != "pending"
    ):
        return None
    task.status = "cancelled"
    await session.flush()
    return task
