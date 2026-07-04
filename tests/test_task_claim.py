import asyncio
from datetime import datetime, timezone

from sqlalchemy import delete

from app.db.models import ScheduledTask
from app.db.session import session_factory
from app.worker import claim_task


async def test_concurrent_claim_wins_exactly_once(session, workspace, user):
    task = ScheduledTask(
        workspace_id=workspace.id,
        user_id=user.id,
        kind="reminder",
        payload={"text": "тест гонки"},
        run_at=datetime.now(timezone.utc),
        status="pending",
    )
    session.add(task)
    await session.commit()

    async def try_claim() -> bool:
        # Отдельная сессия на попытку — как у параллельного свипа
        async with session_factory() as s:
            return await claim_task(s, task.id)

    results = await asyncio.gather(try_claim(), try_claim())
    assert sorted(results) == [False, True]

    await session.refresh(task)
    assert task.status == "running"

    await session.execute(delete(ScheduledTask).where(ScheduledTask.id == task.id))
    await session.commit()


async def test_claim_refuses_non_pending(session, workspace, user):
    task = ScheduledTask(
        workspace_id=workspace.id,
        user_id=user.id,
        kind="reminder",
        payload={},
        run_at=datetime.now(timezone.utc),
        status="done",
    )
    session.add(task)
    await session.commit()

    assert await claim_task(session, task.id) is False

    await session.execute(delete(ScheduledTask).where(ScheduledTask.id == task.id))
    await session.commit()
