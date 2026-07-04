"""Индексы: hnsw на memory_entries.embedding, (workspace_id, id DESC) на messages

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-04

"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Векторный поиск памяти (dedup, ранжирование, search) — без индекса это
    # был бы full scan; NULL-эмбеддинги в hnsw просто не попадают
    op.execute(
        "CREATE INDEX ix_memory_entries_embedding_hnsw ON memory_entries "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    # _load_history: WHERE workspace_id=... ORDER BY id DESC LIMIT n —
    # существующий индекс по created_at такую сортировку не обслуживает
    op.create_index(
        "ix_messages_workspace_id_id",
        "messages",
        ["workspace_id", sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_messages_workspace_id_id", "messages")
    op.drop_index("ix_memory_entries_embedding_hnsw", "memory_entries")
