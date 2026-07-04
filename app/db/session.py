from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

# Пул с запасом: сессия debounce-ответа живёт весь LLM-стрим (до минут),
# при нескольких параллельных чатах дефолтных 5+10 соединений может не хватить
engine = create_async_engine(
    get_settings().database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
