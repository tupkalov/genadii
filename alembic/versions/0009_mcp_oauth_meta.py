"""oauth_meta: срок токена + метаданные auth-сервера для авто-refresh MCP

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-13

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mcp_servers", sa.Column("oauth_meta", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("mcp_servers", "oauth_meta")
