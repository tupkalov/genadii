from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SavedScript(Base):
    """Скрипты, навайбкоженные в песочнице и сохранённые для переиспользования."""

    __tablename__ = "saved_scripts"
    __table_args__ = (
        Index(
            "uq_saved_scripts_workspace_name", "workspace_id", "name", unique=True
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
