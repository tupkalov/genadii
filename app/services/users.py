from aiogram.types import User as TgUser
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserRole


async def get_by_tg_id(session: AsyncSession, tg_id: int) -> User | None:
    return await session.scalar(select(User).where(User.tg_id == tg_id))


async def create_from_tg(
    session: AsyncSession,
    tg_user: TgUser,
    role: UserRole = UserRole.member,
    invited_by_id: int | None = None,
) -> User:
    # Конкурентные апдейты: INSERT ... ON CONFLICT DO NOTHING + SELECT
    await session.execute(
        pg_insert(User)
        .values(
            tg_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            role=role,
            invited_by_id=invited_by_id,
            is_active=True,
        )
        .on_conflict_do_nothing(index_elements=["tg_id"])
    )
    return await get_by_tg_id(session, tg_user.id)


def sync_profile(user: User, tg_user: TgUser) -> None:
    """Обновляет username/имя, если пользователь их сменил в Telegram."""
    if user.username != tg_user.username:
        user.username = tg_user.username
    if user.first_name != tg_user.first_name:
        user.first_name = tg_user.first_name


async def bootstrap_admins(session: AsyncSession, admin_tg_ids: set[int]) -> None:
    """Создаёт админов из ADMIN_TG_IDS при старте приложения."""
    for tg_id in admin_tg_ids:
        user = await get_by_tg_id(session, tg_id)
        if user is None:
            session.add(User(tg_id=tg_id, role=UserRole.admin))
        elif user.role != UserRole.admin:
            user.role = UserRole.admin
    await session.flush()
