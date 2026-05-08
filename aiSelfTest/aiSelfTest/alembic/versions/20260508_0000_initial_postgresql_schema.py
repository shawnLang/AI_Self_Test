"""PostgreSQL 初始数据库基线。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260508_0000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """一次性创建当前业务所需全部表、索引和约束。"""

    op.create_table(
        "client",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("tenant_code", sa.String(length=100), nullable=False),
        sa.Column("tenant_name", sa.String(length=200), nullable=False),
        sa.Column("api_url", sa.String(length=1000), nullable=False),
        sa.Column("account", sa.String(length=50), nullable=False),
        sa.Column("password", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("access_token", sa.String(length=4000), nullable=True),
        sa.Column("refresh_token", sa.String(length=4000), nullable=True),
        sa.Column("expires_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("remark", sa.String(length=1000), nullable=False),
        sa.Column("text", sa.String(length=10000), nullable=False),
        sa.Column("format", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "multimodal_model",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("endpoint_url", sa.String(length=1000), nullable=False),
        sa.Column("api_key", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("detected_models_json", sa.Text(), nullable=True),
        sa.Column("last_detected_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "task",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("config_id", sa.Integer(), nullable=False),
        sa.Column("interval", sa.Integer(), nullable=False),
        sa.Column("filters_json", sa.Text(), nullable=True),
        sa.Column("execution_mode", sa.String(length=10), nullable=False),
        sa.Column("auto_execute", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("execution_status", sa.String(length=10), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("stage_started_at", sa.DateTime(), nullable=True),
        sa.Column("last_progress_at", sa.DateTime(), nullable=True),
        sa.Column("last_pull_end_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_started_at", sa.DateTime(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("current_execution_id", sa.Integer(), nullable=True),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["config_id"], ["config.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_client_id", "task", ["client_id"])
    op.create_index("ix_task_config_id", "task", ["config_id"])
    op.create_index("ix_task_current_execution_id", "task", ["current_execution_id"])

    op.create_table(
        "multimodal_chat_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["multimodal_model.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_multimodal_chat_session_model_id", "multimodal_chat_session", ["model_id"])

    op.create_table(
        "task_execution",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("trigger_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("celery_task_id", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_execution_task_id", "task_execution", ["task_id"])
    op.create_index("ix_task_execution_status", "task_execution", ["status"])
    op.create_index("ix_task_execution_celery_task_id", "task_execution", ["celery_task_id"])
    op.create_index("ix_task_execution_status_updated_at", "task_execution", ["status", "updated_at"])
    op.create_index(
        "ix_task_execution_task_id_created_at",
        "task_execution",
        ["task_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "uq_task_execution_active",
        "task_execution",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "task_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("device_name", sa.String(length=100), nullable=False),
        sa.Column("file_num", sa.String(length=50), nullable=False),
        sa.Column("file_extension", sa.String(length=10), nullable=False),
        sa.Column("file_url", sa.String(length=200), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column("file_fid", sa.String(length=50), nullable=False),
        sa.Column("sp_name_list", sa.String(length=100), nullable=False),
        sa.Column("classify", sa.Integer(), nullable=False),
        sa.Column("file_bmp", sa.Integer(), nullable=False),
        sa.Column("result_file_data", sa.String(length=100), nullable=False),
        sa.Column("id_type", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("down_state", sa.Boolean(), nullable=False),
        sa.Column("down_error", sa.Text(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("llm_state", sa.String(length=20), nullable=False),
        sa.Column("llm_error", sa.Text(), nullable=True),
        sa.Column("llm_at", sa.DateTime(), nullable=True),
        sa.Column("confirm_state", sa.String(length=20), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("remote_state", sa.String(length=20), nullable=False),
        sa.Column("remote_error", sa.Text(), nullable=True),
        sa.Column("remote_at", sa.DateTime(), nullable=True),
        sa.Column("train_state", sa.String(length=20), nullable=False),
        sa.Column("train_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "file_id", name="uq_task_item_task_id_file_id"),
    )
    op.create_index("ix_task_item_task_id", "task_item", ["task_id"])

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
    op.create_index("ix_multimodal_chat_message_session_id", "multimodal_chat_message", ["session_id"])
    op.create_index("ix_multimodal_chat_message_sequence_no", "multimodal_chat_message", ["sequence_no"])

    op.create_table(
        "task_item_data",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_item_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("track_ids", sa.String(length=100), nullable=False),
        sa.Column("sp_amount", sa.Integer(), nullable=False),
        sa.Column("minx", sa.Float(), nullable=True),
        sa.Column("miny", sa.Float(), nullable=True),
        sa.Column("maxx", sa.Float(), nullable=True),
        sa.Column("maxy", sa.Float(), nullable=True),
        sa.Column("llm_name", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["task_item_id"], ["task_item.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_item_data_task_item_id", "task_item_data", ["task_item_id"])


def downgrade() -> None:
    """删除当前基线创建的全部表。"""

    op.drop_index("ix_task_item_data_task_item_id", table_name="task_item_data")
    op.drop_table("task_item_data")
    op.drop_index("ix_multimodal_chat_message_sequence_no", table_name="multimodal_chat_message")
    op.drop_index("ix_multimodal_chat_message_session_id", table_name="multimodal_chat_message")
    op.drop_table("multimodal_chat_message")
    op.drop_index("ix_task_item_task_id", table_name="task_item")
    op.drop_table("task_item")
    op.drop_index("uq_task_execution_active", table_name="task_execution")
    op.drop_index("ix_task_execution_task_id_created_at", table_name="task_execution")
    op.drop_index("ix_task_execution_status_updated_at", table_name="task_execution")
    op.drop_index("ix_task_execution_celery_task_id", table_name="task_execution")
    op.drop_index("ix_task_execution_status", table_name="task_execution")
    op.drop_index("ix_task_execution_task_id", table_name="task_execution")
    op.drop_table("task_execution")
    op.drop_index("ix_multimodal_chat_session_model_id", table_name="multimodal_chat_session")
    op.drop_table("multimodal_chat_session")
    op.drop_index("ix_task_current_execution_id", table_name="task")
    op.drop_index("ix_task_config_id", table_name="task")
    op.drop_index("ix_task_client_id", table_name="task")
    op.drop_table("task")
    op.drop_table("multimodal_model")
    op.drop_table("config")
    op.drop_table("client")
