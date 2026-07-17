"""Глобальный дефолт модели: app_settings + pick_model с ним.

Тесты используют session-фикстуру (rollback на teardown), а set_* только
flush'ат — поэтому AppSetting-строки не протекают в живой инстанс."""
from types import SimpleNamespace

from app.config import get_settings
from app.services import app_settings
from app.services.llm_chat import pick_model


def _ws(**settings):
    return SimpleNamespace(settings=dict(settings))


# --- pick_model: приоритет override → глобальный дефолт → конфиг ---------------


def test_pick_model_uses_default_arg():
    # нет override → берём переданный глобальный дефолт, а не конфиг
    assert pick_model(_ws(), default_model="deepseek/deepseek-v4-flash") == (
        "deepseek/deepseek-v4-flash"
    )


def test_pick_model_override_wins():
    ws = _ws(model_override="anthropic/claude-haiku-4.5")
    assert pick_model(ws, default_model="deepseek/deepseek-v4-flash") == (
        "anthropic/claude-haiku-4.5"
    )


def test_pick_model_falls_back_to_config():
    # default_model=None → конфиг/.env
    assert pick_model(_ws(), default_model=None) == get_settings().default_model


# --- app_settings: get/set/reset глобального дефолта --------------------------


async def test_default_model_falls_back_to_config(session):
    # Ключа в БД нет → значение из конфига
    await app_settings.reset_default_model(session)
    assert await app_settings.default_model(session) == get_settings().default_model


async def test_set_and_get_default_model(session):
    await app_settings.set_default_model(session, "google/gemini-2.5-flash")
    assert await app_settings.default_model(session) == "google/gemini-2.5-flash"


async def test_reset_default_model(session):
    await app_settings.set_default_model(session, "google/gemini-2.5-flash")
    await app_settings.reset_default_model(session)
    assert await app_settings.default_model(session) == get_settings().default_model


async def test_generic_kv_roundtrip(session):
    await app_settings.set_value(session, "some_key", {"a": 1})
    assert await app_settings.get_value(session, "some_key") == {"a": 1}
    await app_settings.delete_value(session, "some_key")
    assert await app_settings.get_value(session, "some_key") is None
