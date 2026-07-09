"""MCP-серверы и входящие вебхуки (per-workspace)

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-09

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.BigInteger(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("auth_token", sa.String(512)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("tools_cache", JSONB),
        sa.Column("cached_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "uq_mcp_servers_workspace_name",
        "mcp_servers",
        ["workspace_id", "name"],
        unique=True,
    )

    op.create_table(
        "webhooks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.BigInteger(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False, server_default="notify"),
        sa.Column("instruction", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("last_fired_at", sa.DateTime(timezone=True)),
        sa.Column("fire_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "uq_webhooks_workspace_name", "webhooks", ["workspace_id", "name"], unique=True
    )
    op.create_index("uq_webhooks_token", "webhooks", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_webhooks_token", "webhooks")
    op.drop_index("uq_webhooks_workspace_name", "webhooks")
    op.drop_table("webhooks")
    op.drop_index("uq_mcp_servers_workspace_name", "mcp_servers")
    op.drop_table("mcp_servers")
