"""models: каталог моделей OpenRouter с ценами (синк) — allowlist + ценовой потолок

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-20

"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "models",
        sa.Column("id", sa.String(128), primary_key=True),  # vendor/model
        sa.Column("name", sa.String(256), nullable=False),
        # Цены за 1M токенов ($). Numeric — деньги без плавающих артефактов.
        sa.Column("price_in", sa.Numeric(12, 4), nullable=False),
        sa.Column("price_out", sa.Numeric(12, 4), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("models")
