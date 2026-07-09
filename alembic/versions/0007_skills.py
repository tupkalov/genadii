"""Скиллы + привязка вебхуков к скиллам

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-09

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.BigInteger(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("allowed_tools", JSONB),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "uq_skills_workspace_name", "skills", ["workspace_id", "name"], unique=True
    )
    op.add_column(
        "webhooks",
        sa.Column(
            "skill_id",
            sa.BigInteger(),
            sa.ForeignKey("skills.id", ondelete="SET NULL"),
        ),
    )


def downgrade() -> None:
    op.drop_column("webhooks", "skill_id")
    op.drop_index("uq_skills_workspace_name", "skills")
    op.drop_table("skills")
