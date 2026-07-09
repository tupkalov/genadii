from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Webhook(Base):
    """Входящий вебхук workspace'а: POST /hooks/{token} → уведомление или агент."""

    __tablename__ = "webhooks"
    __table_args__ = (
        Index("uq_webhooks_workspace_name", "workspace_id", "name", unique=True),
        Index("uq_webhooks_token", "token", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(64))
    token: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16), default="notify")  # notify | agent
    instruction: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fire_count: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
