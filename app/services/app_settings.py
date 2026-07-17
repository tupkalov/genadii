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

DEFAULT_MODEL_KEY = "default_model"


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


async def default_model(session: AsyncSession) -> str:
    """Глобальный дефолт модели: из БД, иначе из конфига/.env."""
    value = await get_value(session, DEFAULT_MODEL_KEY)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return get_settings().default_model


async def set_default_model(session: AsyncSession, model: str) -> None:
    await set_value(session, DEFAULT_MODEL_KEY, model.strip())


async def reset_default_model(session: AsyncSession) -> None:
    """Убрать БД-оверрайд — вернуться к значению из конфига/.env."""
    await delete_value(session, DEFAULT_MODEL_KEY)
