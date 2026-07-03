import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MemoryEntry, User, Workspace
from app.llm import embeddings

logger = logging.getLogger("gennady.memory")

PROMPT_FACTS_LIMIT = 25  # сколько последних фактов инлайним в system prompt


async def add_fact(
    session: AsyncSession, workspace: Workspace, user: User, content: str
) -> MemoryEntry:
    # Сбой embeddings не должен ронять запоминание: сохраняем без вектора,
    # cron reindex_memory в worker'е доиндексирует позже.
    try:
        embedding = await embeddings.embed(content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Embedding не получился, факт сохраняю без него: %s", exc)
        embedding = None

    entry = MemoryEntry(
        workspace_id=workspace.id,
        kind="fact",
        content=content.strip(),
        embedding=embedding,
        created_by_id=user.id,
    )
    session.add(entry)
    await session.flush()
    return entry


async def list_facts(
    session: AsyncSession, workspace: Workspace, limit: int = PROMPT_FACTS_LIMIT
) -> list[MemoryEntry]:
    return list(
        (
            await session.execute(
                select(MemoryEntry)
                .where(
                    MemoryEntry.workspace_id == workspace.id,
                    MemoryEntry.archived_at.is_(None),
                )
                .order_by(MemoryEntry.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def search(
    session: AsyncSession, workspace: Workspace, query: str, limit: int = 5
) -> list[MemoryEntry]:
    """Семантический поиск (pgvector), с фолбэком на текстовый ILIKE."""
    found: dict[int, MemoryEntry] = {}

    try:
        query_vector = await embeddings.embed(query)
    except Exception as exc:  # noqa: BLE001 — деградируем до ILIKE
        logger.warning("Embedding запроса не получился, ищу текстом: %s", exc)
        query_vector = None
    if query_vector is not None:
        rows = (
            await session.execute(
                select(MemoryEntry)
                .where(
                    MemoryEntry.workspace_id == workspace.id,
                    MemoryEntry.archived_at.is_(None),
                    MemoryEntry.embedding.isnot(None),
                )
                .order_by(MemoryEntry.embedding.cosine_distance(query_vector))
                .limit(limit)
            )
        ).scalars()
        found.update({e.id: e for e in rows})

    rows = (
        await session.execute(
            select(MemoryEntry)
            .where(
                MemoryEntry.workspace_id == workspace.id,
                MemoryEntry.archived_at.is_(None),
                MemoryEntry.content.ilike(f"%{query}%"),
            )
            .order_by(MemoryEntry.id.desc())
            .limit(limit)
        )
    ).scalars()
    found.update({e.id: e for e in rows})

    return list(found.values())[:limit]


async def archive_fact(
    session: AsyncSession, workspace: Workspace, fact_id: int
) -> MemoryEntry | None:
    from sqlalchemy import func

    entry = await session.get(MemoryEntry, fact_id)
    if (
        entry is None
        or entry.workspace_id != workspace.id
        or entry.archived_at is not None
    ):
        return None
    entry.archived_at = func.now()
    await session.flush()
    return entry
