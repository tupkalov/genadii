"""saved scripts

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-03

"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_scripts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.BigInteger(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("code", sa.Text(), nullable=False),
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
        "uq_saved_scripts_workspace_name",
        "saved_scripts",
        ["workspace_id", "name"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("saved_scripts")
