from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Skill(Base):
    """Именованный сценарий workspace'а: инструкция + ограничение инструментов.

    Запускается слэш-командой /имя, вебхуком, кроном или самим ботом.
    allowed_tools — список имён/масок (mcp_hubhead_*); NULL = все инструменты.
    """

    __tablename__ = "skills"
    __table_args__ = (
        Index("uq_skills_workspace_name", "workspace_id", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(32))
    instruction: Mapped[str] = mapped_column(Text)
    allowed_tools: Mapped[list[str] | None] = mapped_column(JSONB)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
