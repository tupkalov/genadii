from aiogram import Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.errors import on_error
from app.bot.handlers import (
    admin,
    budget,
    chat,
    digest,
    history_edit,
    mcp,
    memory,
    model,
    persona,
    proactive,
    reminders,
    scripts,
    search,
    service,
    start,
    stats,
    tools,
    webhooks,
    whoami,
)
from app.bot.middlewares.auth import AuthMiddleware
from app.bot.middlewares.db import DbSessionMiddleware
from app.bot.middlewares.throttle import ThrottleMiddleware
from app.bot.middlewares.workspace import WorkspaceMiddleware
from app.config import get_settings


async def _mark_skip_save(handler, event: TelegramObject, data: dict):
    """Для edited_message: workspace-миддлварь не должна сохранять правку как новое."""
    data["_skip_save"] = True
    return await handler(event, data)


def create_dispatcher(session_factory: async_sessionmaker) -> Dispatcher:
    storage = RedisStorage.from_url(get_settings().redis_url)
    dp = Dispatcher(storage=storage)

    db_mw = DbSessionMiddleware(session_factory)
    auth_mw = AuthMiddleware()
    throttle_mw = ThrottleMiddleware()
    workspace_mw = WorkspaceMiddleware()

    # message: сессия БД -> throttle -> auth (whitelist) -> workspace + сохранение
    dp.message.outer_middleware(db_mw)
    dp.message.outer_middleware(throttle_mw)
    dp.message.outer_middleware(auth_mw)
    dp.message.outer_middleware(workspace_mw)

    # edited_message: та же цепочка, но без throttle и без сохранения как нового
    dp.edited_message.outer_middleware(db_mw)
    dp.edited_message.outer_middleware(auth_mw)
    dp.edited_message.outer_middleware(_mark_skip_save)
    dp.edited_message.outer_middleware(workspace_mw)

    # callback_query: тот же whitelist и workspace, без throttle (низкий объём)
    dp.callback_query.outer_middleware(db_mw)
    dp.callback_query.outer_middleware(auth_mw)
    dp.callback_query.outer_middleware(workspace_mw)

    dp.errors.register(on_error)

    dp.include_router(service.message_router)  # миграция чата — до catch-all
    dp.include_router(start.router)
    dp.include_router(admin.router)
    dp.include_router(whoami.router)
    dp.include_router(persona.router)  # FSM-онбординг — до catch-all
    dp.include_router(model.router)
    dp.include_router(stats.router)
    dp.include_router(tools.router)
    dp.include_router(memory.router)
    dp.include_router(reminders.router)
    dp.include_router(budget.router)
    dp.include_router(scripts.router)
    dp.include_router(proactive.router)
    dp.include_router(digest.router)
    dp.include_router(history_edit.router)
    dp.include_router(search.router)
    dp.include_router(mcp.router)
    dp.include_router(webhooks.router)
    dp.include_router(chat.router)  # catch-all — всегда последним

    dp.include_router(service.edited_router)

    return dp
