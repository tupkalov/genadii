import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi import FastAPI

from app.api.routes import dashboard, health, logs, stats
from app.bot.commands import setup_bot_commands
from app.bot.setup import create_dispatcher
from app.config import get_settings
from app.db.session import session_factory
from app.llm import http as llm_http
from app.services import users

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gennady")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Бутстрап админов из ADMIN_TG_IDS
    async with session_factory() as session:
        await users.bootstrap_admins(session, settings.admin_ids)
        await session.commit()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = create_dispatcher(session_factory)

    me = await bot.me()
    dp["bot_username"] = me.username
    await setup_bot_commands(bot, settings.admin_ids)
    logger.info("Запускаю Умного Геннадия: @%s", me.username)

    polling_task = asyncio.create_task(
        dp.start_polling(bot, handle_signals=False), name="tg-polling"
    )
    app.state.bot = bot

    yield

    logger.info("Останавливаю поллинг...")
    await dp.stop_polling()
    polling_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await polling_task
    await bot.session.close()
    await llm_http.aclose()


app = FastAPI(title="Умный Геннадий", lifespan=lifespan)
app.include_router(health.router)
app.include_router(stats.router)
app.include_router(logs.router)
app.include_router(dashboard.router)
