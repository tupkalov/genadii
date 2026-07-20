"""Каталог моделей: блендованная цена, потолок, автопонижение.

ВАЖНО: тесты идут по РЕАЛЬНОЙ БД. ModelInfo и Workspace создаём БЕЗ commit —
опираемся на видимость в своей сессии (autoflush) и откат на teardown. Не
используем фикстуру `workspace` (её teardown делает commit и «протёк» бы
тестовыми моделями/правками reconcile по реальным чатам)."""
import random
from decimal import Decimal

from app.db.models import ModelInfo, Workspace, WorkspaceType
from app.services import models_catalog


async def _add(session, mid, pin, pout, active=True):
    session.add(ModelInfo(
        id=mid, name=mid, price_in=Decimal(str(pin)),
        price_out=Decimal(str(pout)), active=active,
    ))
    await session.flush()


async def _mk_ws(session, **settings):
    ws = Workspace(
        type=WorkspaceType.personal,
        tg_chat_id=-random.randint(10**15, 2 * 10**15),
        settings=settings,
    )
    session.add(ws)
    await session.flush()
    return ws


def test_blended_weights_input_heavy():
    # вход весит 22, выход 1 — под наш профиль
    assert models_catalog.blended(1, 0) == 22
    assert models_catalog.blended(0, 1) == 1
    assert models_catalog.blended(0.10, 0.40) == 0.10 * 22 + 0.40


async def test_within_cap(session):
    await _add(session, "t/cheap", 0.10, 0.40)
    await _add(session, "t/mid", 0.30, 2.50)
    await _add(session, "t/pricey", 2, 10)
    assert await models_catalog.within_cap(session, "t/cheap", "t/mid") is True
    assert await models_catalog.within_cap(session, "t/mid", "t/mid") is True   # равно — ок
    assert await models_catalog.within_cap(session, "t/pricey", "t/mid") is False
    assert await models_catalog.within_cap(session, "t/none", "t/mid") is False  # неизвестная


async def test_is_known(session):
    await _add(session, "t/on", 1, 1)
    await _add(session, "t/off", 1, 1, active=False)
    assert await models_catalog.is_known(session, "t/on") is True
    assert await models_catalog.is_known(session, "t/off") is False
    assert await models_catalog.is_known(session, "t/absent") is False


async def test_cheapest_sorted_ascending(session):
    await _add(session, "t/z", 9, 9)
    await _add(session, "t/y", 0.01, 0.01)
    rows = await models_catalog.cheapest(session, limit=200)
    scores = [models_catalog.blended(r.price_in, r.price_out) for r in rows]
    assert scores == sorted(scores)  # дешёвые сверху


async def test_reconcile_downgrades_expensive_override(session):
    await _add(session, "t/newcheap", 0.10, 0.40)
    await _add(session, "t/wasexpensive", 2, 10)
    ws = await _mk_ws(session, workhorse="t/wasexpensive")

    changes = await models_catalog.reconcile_overrides(session, "workhorse", "t/newcheap")

    assert any(c["workspace_id"] == ws.id for c in changes)
    assert "workhorse" not in (ws.settings or {})  # сброшен → наследует дефолт


async def test_reconcile_keeps_cheaper_override(session):
    await _add(session, "t/defsmart", 2, 10)
    await _add(session, "t/cheapersmart", 0.30, 2.50)
    ws = await _mk_ws(session, smart="t/cheapersmart")

    changes = await models_catalog.reconcile_overrides(session, "smart", "t/defsmart")

    assert (ws.settings or {}).get("smart") == "t/cheapersmart"  # дешевле — не трогаем
    assert all(c["workspace_id"] != ws.id for c in changes)
