from fastapi import APIRouter
from redis.asyncio import Redis
from sqlalchemy import text

from app.config import get_settings
from app.db.session import engine

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    db_ok = False
    redis_ok = False

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    try:
        redis = Redis.from_url(get_settings().redis_url)
        redis_ok = bool(await redis.ping())
        await redis.aclose()
    except Exception:
        pass

    return {
        "status": "ok" if db_ok and redis_ok else "degraded",
        "db": db_ok,
        "redis": redis_ok,
    }
