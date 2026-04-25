"""新增多模态聊天会话与消息表。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260423_0001"
down_revision = "20260423_0000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级到包含多模态聊天会话与消息表的版本。"""

    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())
    if "multimodal_chat_session" in existing_tables:
        return

    op.create_table(
        "multimodal_chat_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_message_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["multimodal_model.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_multimodal_chat_session_model_id",
        "multimodal_chat_session",
        ["model_id"],
        unique=False,
    )

    op.create_table(
        "multimodal_chat_message",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("attachments_json", sa.Text(), nullable=True),
        sa.Column("used_url", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["multimodal_chat_session.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_multimodal_chat_message_session_id",
        "multimodal_chat_message",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_multimodal_chat_message_sequence_no",
        "multimodal_chat_message",
        ["sequence_no"],
        unique=False,
    )


def downgrade() -> None:
    """回滚多模态聊天会话与消息表。"""

    op.drop_index("ix_multimodal_chat_message_sequence_no", table_name="multimodal_chat_message")
    op.drop_index("ix_multimodal_chat_message_session_id", table_name="multimodal_chat_message")
    op.drop_table("multimodal_chat_message")

    op.drop_index("ix_multimodal_chat_session_model_id", table_name="multimodal_chat_session")
    op.drop_table("multimodal_chat_session")
