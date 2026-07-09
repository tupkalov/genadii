"""OAuth-колонки для MCP-серверов

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-09

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mcp_servers", sa.Column("oauth_client_info", JSONB))
    op.add_column("mcp_servers", sa.Column("oauth_tokens", JSONB))


def downgrade() -> None:
    op.drop_column("mcp_servers", "oauth_tokens")
    op.drop_column("mcp_servers", "oauth_client_info")
