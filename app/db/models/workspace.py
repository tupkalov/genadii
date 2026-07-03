import enum
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkspaceType(str, enum.Enum):
    personal = "personal"
    group = "group"


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[WorkspaceType] = mapped_column(
        Enum(WorkspaceType, native_enum=False, length=16)
    )
    tg_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(256))
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16), default="member")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
