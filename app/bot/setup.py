from aiogram import Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.errors import on_error
from app.bot.handlers import (
    admin,
    budget,
    chat,
    memory,
    model,
    persona,
    reminders,
    scripts,
    start,
    stats,
    tools,
    whoami,
)
from app.bot.middlewares.auth import AuthMiddleware
from app.bot.middlewares.db import DbSessionMiddleware
from app.bot.middlewares.workspace import WorkspaceMiddleware
from app.config import get_settings


def create_dispatcher(session_factory: async_sessionmaker) -> Dispatcher:
    storage = RedisStorage.from_url(get_settings().redis_url)
    dp = Dispatcher(storage=storage)

    # Порядок важен: сессия БД -> auth (whitelist) -> workspace + сохранение сообщений
    dp.message.outer_middleware(DbSessionMiddleware(session_factory))
    dp.message.outer_middleware(AuthMiddleware())
    dp.message.outer_middleware(WorkspaceMiddleware())

    dp.errors.register(on_error)

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
    dp.include_router(chat.router)  # catch-all — всегда последним

    return dp
