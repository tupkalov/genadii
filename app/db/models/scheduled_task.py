from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ScheduledTask(Base):
    """Напоминания и long-running задачи (исполнение — с Milestone 5)."""

    __tablename__ = "scheduled_tasks"
    __table_args__ = (Index("ix_scheduled_tasks_status_run_at", "status", "run_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(32), default="reminder")
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cron: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
