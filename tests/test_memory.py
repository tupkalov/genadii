from app.llm import embeddings
from app.services import memory

FIRST = "у Аси день рождения 5 мая"
SECOND = "на самом деле у Аси день рождения 6 мая"
UNRELATED = "Аня любит собак"


def _vec(cos_component: float) -> list[float]:
    """Двумерный (остальное — нули) единичный вектор с заданной первой координатой,
    чтобы cosine_distance между двумя такими векторами был предсказуем."""
    y = (1 - cos_component**2) ** 0.5
    return [cos_component, y] + [0.0] * 1534


_VECTORS = {FIRST: _vec(1.0), SECOND: _vec(0.99), UNRELATED: _vec(0.0)}


async def _mock_embed(text: str) -> list[float]:
    return _VECTORS[text]


def _patch_embed(monkeypatch):
    monkeypatch.setattr(embeddings, "embed", _mock_embed)


async def test_add_fact_supersedes_similar_fact(session, workspace, user, monkeypatch):
    _patch_embed(monkeypatch)

    first = await memory.add_fact(session, workspace, user, FIRST)
    await session.commit()
    second = await memory.add_fact(session, workspace, user, SECOND)
    await session.commit()

    await session.refresh(first)
    assert first.archived_at is not None
    assert second.archived_at is None

    facts = await memory.list_facts(session, workspace)
    contents = {f.content for f in facts}
    assert SECOND in contents
    assert FIRST not in contents


async def test_add_fact_keeps_unrelated_facts(session, workspace, user, monkeypatch):
    _patch_embed(monkeypatch)

    first = await memory.add_fact(session, workspace, user, FIRST)
    await memory.add_fact(session, workspace, user, UNRELATED)
    await session.commit()

    await session.refresh(first)
    assert first.archived_at is None

    facts = await memory.list_facts(session, workspace)
    assert len(facts) == 2


async def test_list_facts_ranks_by_relevance_over_recency(
    session, workspace, user, monkeypatch
):
    _patch_embed(monkeypatch)

    await memory.add_fact(session, workspace, user, FIRST)  # старше, но релевантен запросу
    await memory.add_fact(session, workspace, user, UNRELATED)  # новее, но не по теме
    await session.commit()

    facts = await memory.list_facts(session, workspace, query_text=FIRST)
    assert facts[0].content == FIRST


async def test_list_facts_without_query_is_recency_order(
    session, workspace, user, monkeypatch
):
    _patch_embed(monkeypatch)

    await memory.add_fact(session, workspace, user, FIRST)
    await memory.add_fact(session, workspace, user, UNRELATED)
    await session.commit()

    facts = await memory.list_facts(session, workspace)
    assert facts[0].content == UNRELATED  # последний добавленный — первый по recency
