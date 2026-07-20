"""Глобальные настройки уровня приложения (общие для всех чатов).

Пока единственная — глобальный дефолт модели, который админ может задать прямо
из чата (/model default <id>) без правки .env и рестарта. Хранится в БД, поэтому
переживает рестарт и виден всем процессам (app + worker). Фолбэк — значение из
конфига/.env (settings.default_model), если в БД ничего не задано.

set_* только flush'ат (без commit) — коммитит вызывающий хендлер; в тестах с
session-фикстурой это значит автоматический откат, без «протечки» в живой инстанс.
"""
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import AppSetting

DEFAULT_MODEL_KEY = "default_model"  # глобальный workhorse
DEFAULT_SMART_KEY = "default_smart"  # глобальный smart (эскалация)


async def get_value(session: AsyncSession, key: str) -> Any | None:
    row = await session.get(AppSetting, key)
    return row.value if row is not None else None


async def set_value(session: AsyncSession, key: str, value: Any) -> None:
    row = await session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    await session.flush()


async def delete_value(session: AsyncSession, key: str) -> None:
    row = await session.get(AppSetting, key)
    if row is not None:
        await session.delete(row)
        await session.flush()


async def workhorse_default(session: AsyncSession) -> str:
    """Глобальный workhorse (дешёвая первая линия): БД, иначе конфиг/.env."""
    value = await get_value(session, DEFAULT_MODEL_KEY)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return get_settings().default_model


async def smart_default(session: AsyncSession) -> str:
    """Глобальный smart (эскалация): БД, иначе конфиг/.env."""
    value = await get_value(session, DEFAULT_SMART_KEY)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return get_settings().smart_model


async def set_tier_default(session: AsyncSession, tier: str, model: str) -> None:
    key = DEFAULT_SMART_KEY if tier == "smart" else DEFAULT_MODEL_KEY
    await set_value(session, key, model.strip())


async def reset_tier_default(session: AsyncSession, tier: str) -> None:
    key = DEFAULT_SMART_KEY if tier == "smart" else DEFAULT_MODEL_KEY
    await delete_value(session, key)


# --- Обратная совместимость (старое API = workhorse) --------------------------


async def default_model(session: AsyncSession) -> str:
    return await workhorse_default(session)


async def set_default_model(session: AsyncSession, model: str) -> None:
    await set_tier_default(session, "workhorse", model)


async def reset_default_model(session: AsyncSession) -> None:
    await reset_tier_default(session, "workhorse")
