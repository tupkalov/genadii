"""file_id медиа в сообщениях — чтобы подтягивать фото из истории в vision

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-11

"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("media_file_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "media_file_id")
