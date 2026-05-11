"""新增任务级提交保存执行记录。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260509_0003"
down_revision = "20260509_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建任务级提交保存执行记录表。"""

    op.create_table(
        "task_submission",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("celery_task_id", sa.String(length=100), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("current_task_item_id", sa.Integer(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_submission_task_id", "task_submission", ["task_id"])
    op.create_index("ix_task_submission_status", "task_submission", ["status"])
    op.create_index("ix_task_submission_celery_task_id", "task_submission", ["celery_task_id"])
    op.create_index("ix_task_submission_current_task_item_id", "task_submission", ["current_task_item_id"])


def downgrade() -> None:
    """删除任务级提交保存执行记录表。"""

    op.drop_index("ix_task_submission_current_task_item_id", table_name="task_submission")
    op.drop_index("ix_task_submission_celery_task_id", table_name="task_submission")
    op.drop_index("ix_task_submission_status", table_name="task_submission")
    op.drop_index("ix_task_submission_task_id", table_name="task_submission")
    op.drop_table("task_submission")
