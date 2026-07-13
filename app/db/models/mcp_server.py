from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class McpServer(Base):
    """Подключённый MCP-сервер workspace'а: его инструменты добавляются боту."""

    __tablename__ = "mcp_servers"
    __table_args__ = (
        Index("uq_mcp_servers_workspace_name", "workspace_id", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(String(512))
    auth_token: Mapped[str | None] = mapped_column(String(512))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Последний discovered список [{name, description, input_schema}] —
    # для /mcp list без коннекта и как фолбэк при холодном Redis
    tools_cache: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    # OAuth: данные динамической регистрации клиента и выданные токены
    # (обновляются SDK при refresh через DbTokenStorage)
    oauth_client_info: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    oauth_tokens: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # expires_at токена + метаданные auth-сервера (token_endpoint) — чтобы
    # неинтерактивный провайдер сам обновлял токен по refresh_token
    oauth_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    cached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
