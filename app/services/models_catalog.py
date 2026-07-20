"""Каталог моделей OpenRouter: синк цен + сравнение «не дороже дефолта».

Синкается кроном из публичного /models. Даёт: allowlist (что можно ставить),
цены и блендованную оценку стоимости под НАШ профиль (вход сильно доминирует),
по которой участники могут менять модель только на не-дороже дефолта своего тира.
"""
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ModelInfo, Workspace
from app.llm import http as llm_http

logger = logging.getLogger("gennady.models")

MODELS_URL = "https://openrouter.ai/api/v1/models"

# Блендованный вес под наш реальный расход (~7.8M вход / 0.35M выход ≈ 22:1).
# score = цена_входа*22 + цена_выхода — «сколько примерно стоит наш типичный ход».
IN_WEIGHT = 22
OUT_WEIGHT = 1


def blended(price_in: Decimal | float, price_out: Decimal | float) -> float:
    return float(price_in) * IN_WEIGHT + float(price_out) * OUT_WEIGHT


async def sync(session: AsyncSession) -> int:
    """Тянет каталог из OpenRouter и upsert'ит в таблицу models. Возвращает
    число обработанных моделей. Цены — за 1M токенов."""
    resp = await llm_http.client.get(MODELS_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    seen = 0
    for m in data:
        model_id = m.get("id")
        if not model_id:
            continue
        pricing = m.get("pricing") or {}
        try:
            # OpenRouter отдаёт цену за токен строкой — переводим в $/1M
            price_in = Decimal(str(pricing.get("prompt", "0"))) * 1_000_000
            price_out = Decimal(str(pricing.get("completion", "0"))) * 1_000_000
        except (TypeError, ValueError, ArithmeticError):
            continue
        if price_in < 0 or price_out < 0:  # спец-значения (-1) — пропускаем
            continue
        row = await session.get(ModelInfo, model_id)
        if row is None:
            session.add(
                ModelInfo(
                    id=model_id,
                    name=(m.get("name") or model_id)[:256],
                    price_in=price_in,
                    price_out=price_out,
                    active=True,
                )
            )
        else:
            row.name = (m.get("name") or model_id)[:256]
            row.price_in = price_in
            row.price_out = price_out
            row.active = True
        seen += 1
    await session.commit()
    logger.info("Каталог моделей синкнут: %s моделей", seen)
    return seen


async def get(session: AsyncSession, model_id: str) -> ModelInfo | None:
    return await session.get(ModelInfo, model_id)


async def score(session: AsyncSession, model_id: str) -> float | None:
    """Блендованная стоимость модели, None — если модели нет в каталоге."""
    row = await get(session, model_id)
    if row is None:
        return None
    return blended(row.price_in, row.price_out)


async def within_cap(
    session: AsyncSession, model_id: str, cap_model_id: str
) -> bool:
    """Модель не дороже дефолта тира (cap_model_id)? Неизвестная модель или
    неизвестный дефолт → считаем НЕ проходящей (для участников — запрет)."""
    candidate = await score(session, model_id)
    cap = await score(session, cap_model_id)
    if candidate is None or cap is None:
        return False
    # маленький допуск на плавающие артефакты
    return candidate <= cap + 1e-9


async def is_known(session: AsyncSession, model_id: str) -> bool:
    row = await get(session, model_id)
    return row is not None and row.active


async def reconcile_overrides(
    session: AsyncSession, tier: str, new_default_id: str
) -> list[dict]:
    """Дефолт тира удешевили → per-chat оверрайды, ставшие дороже него (или
    неизвестные каталогу), сбрасываем, чтобы чат наследовал новый дефолт.
    Возвращает список изменений [{workspace_id, tier, from, to}] для лога.
    Сессию НЕ коммитит — это делает вызывающий."""
    cap = await score(session, new_default_id)
    if cap is None:  # неизвестный новый дефолт — не с чем сравнивать
        return []
    key = "smart" if tier == "smart" else "workhorse"
    changed: list[dict] = []
    workspaces = (await session.scalars(select(Workspace))).all()
    for ws in workspaces:
        s = ws.settings or {}
        current = s.get(key)
        # старый общий пин model_override относим к тиру workhorse
        if current is None and key == "workhorse":
            current = s.get("model_override")
        if not current:
            continue
        cur = await score(session, current)
        if cur is None or cur > cap + 1e-9:
            new_s = dict(s)
            new_s.pop(key, None)
            if key == "workhorse":
                new_s.pop("model_override", None)
            ws.settings = new_s
            changed.append(
                {"workspace_id": ws.id, "tier": tier, "from": current, "to": new_default_id}
            )
    return changed


async def cheapest(session: AsyncSession, limit: int = 15) -> list[ModelInfo]:
    """Активные модели, отсортированные по блендованной цене (дешёвые первыми)."""
    rows = (await session.scalars(select(ModelInfo).where(ModelInfo.active))).all()
    rows.sort(key=lambda r: blended(r.price_in, r.price_out))
    return rows[:limit]


# Подборка узнаваемых моделей по тирам для /model list — иначе список забивают
# бесплатные/безымянные (самые дешёвые), а популярных не видно. Несуществующие
# в каталоге id просто отсеиваются. Обновлять редко, вручную.
FEATURED = [
    "openai/gpt-5-nano",
    "deepseek/deepseek-v4-flash",
    "google/gemini-2.5-flash-lite",
    "meta-llama/llama-3.3-70b-instruct",
    "deepseek/deepseek-chat",
    "openai/gpt-5-mini",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-v4-pro",
    "mistralai/mistral-medium-3.1",
    "openai/gpt-5.4-mini",
    "qwen/qwen3-max",
    "anthropic/claude-haiku-4.5",
    "openai/gpt-5",
    "google/gemini-2.5-pro",
    "anthropic/claude-sonnet-5",
    "anthropic/claude-opus-4.8",
]


async def featured(session: AsyncSession) -> list[ModelInfo]:
    """Популярные модели из подборки, что есть в каталоге, дешёвые сверху."""
    rows = []
    for model_id in FEATURED:
        row = await get(session, model_id)
        if row is not None and row.active:
            rows.append(row)
    rows.sort(key=lambda r: blended(r.price_in, r.price_out))
    return rows
