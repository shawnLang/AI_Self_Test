"""create initial aiSelfTest schema

Revision ID: 20260417_0001
Revises:
Create Date: 2026-04-17
"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "20260417_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("apiUrl", sa.String(), nullable=False),
        sa.Column("account", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("password", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("access_token", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("refresh_token", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("expires_in", sa.Integer(), nullable=True),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("interval", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("filters_json", sa.Text(), nullable=True),
        sa.Column("execution_mode", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("auto_confirm", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("execution_status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("finished_at", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("last_error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
    )
    op.create_table(
        "reviews",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), primary_key=True, nullable=False),
        sa.Column("image_url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("original_result", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sp_name_list", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("ai_result", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("detail_snapshot_json", sa.Text(), nullable=True),
        sa.Column("review_rows_json", sa.Text(), nullable=True),
        sa.Column("confirm_state", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("confirm_attempted_at", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("confirmed_at", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("remote_error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("updated_at", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("task_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column("media_type", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("media_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("file_time", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
    )
    op.create_table(
        "multimodal_models",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("model_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("endpoint_url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("api_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("detected_models_json", sa.Text(), nullable=True),
        sa.Column("last_detected_at", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("updated_at", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("multimodal_models")
    op.drop_table("reviews")
    op.drop_table("tasks")
    op.drop_table("clients")
