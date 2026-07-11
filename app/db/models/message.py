import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    system = "system"
    tool = "tool"


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, native_enum=False, length=16)
    )
    content: Mapped[str] = mapped_column(Text)
    # file_id вложения (фото) — чтобы перекачать картинку из истории в vision,
    # когда о ней спрашивают позже без реплая. Хранится только сам id.
    media_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
