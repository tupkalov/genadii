"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-03

"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JSONB_EMPTY = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(64)),
        sa.Column("first_name", sa.String(128)),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("invited_by_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_users_tg_id", "users", ["tg_id"], unique=True)

    op.create_table(
        "workspaces",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("tg_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(256)),
        sa.Column(
            "settings", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_workspaces_tg_chat_id", "workspaces", ["tg_chat_id"], unique=True)

    op.create_table(
        "workspace_members",
        sa.Column(
            "workspace_id",
            sa.BigInteger(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.BigInteger(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("tg_message_id", sa.BigInteger()),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_messages_workspace_created", "messages", ["workspace_id", "created_at"]
    )

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.BigInteger(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.BigInteger(),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
        ),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "completion_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_llm_usage_workspace_id", "llm_usage", ["workspace_id"])

    op.create_table(
        "memory_entries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.BigInteger(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False, server_default="fact"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536)),
        sa.Column("created_by_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_memory_entries_workspace_id", "memory_entries", ["workspace_id"])

    op.create_table(
        "tool_permissions",
        sa.Column(
            "workspace_id",
            sa.BigInteger(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tool_name", sa.String(64), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("granted_by_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.BigInteger(),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
        ),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])

    op.create_table(
        "scheduled_tasks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.BigInteger(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False, server_default="reminder"),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY
        ),
        sa.Column("run_at", sa.DateTime(timezone=True)),
        sa.Column("cron", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_scheduled_tasks_status_run_at", "scheduled_tasks", ["status", "run_at"]
    )


def downgrade() -> None:
    op.drop_table("scheduled_tasks")
    op.drop_table("audit_log")
    op.drop_table("tool_permissions")
    op.drop_table("memory_entries")
    op.drop_table("llm_usage")
    op.drop_table("messages")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
    op.drop_table("users")
