from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ModelInfo(Base):
    """Модель из каталога OpenRouter (синкается кроном). Служит и allowlist'ом
    (какие модели вообще можно ставить), и источником цен для потолка «не дороже
    дефолта». Цены — за 1M токенов, $."""

    __tablename__ = "models"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # vendor/model
    name: Mapped[str] = mapped_column(String(256))
    price_in: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    price_out: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
