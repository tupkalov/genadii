"""llm_usage.user_id

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-03

"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_usage", sa.Column("user_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_llm_usage_user_id_users",
        "llm_usage",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_llm_usage_user_id", "llm_usage", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_user_id", "llm_usage")
    op.drop_constraint("fk_llm_usage_user_id_users", "llm_usage", type_="foreignkey")
    op.drop_column("llm_usage", "user_id")
