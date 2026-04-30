"""补充任务运行游标字段。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260425_0002"
down_revision = "20260425_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """为任务执行链补充运行时字段与唯一约束。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    task_columns = {column["name"] for column in inspector.get_columns("task")}
    with op.batch_alter_table("task") as batch_op:
        if "last_pull_end_at" not in task_columns:
            batch_op.add_column(sa.Column("last_pull_end_at", sa.DateTime(), nullable=True))
        if "last_run_started_at" not in task_columns:
            batch_op.add_column(sa.Column("last_run_started_at", sa.DateTime(), nullable=True))
        if "skipped_count" not in task_columns:
            batch_op.add_column(sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    """回滚任务运行字段。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    task_columns = {column["name"] for column in inspector.get_columns("task")}
    with op.batch_alter_table("task") as batch_op:
        if "skipped_count" in task_columns:
            batch_op.drop_column("skipped_count")
        if "last_run_started_at" in task_columns:
            batch_op.drop_column("last_run_started_at")
        if "last_pull_end_at" in task_columns:
            batch_op.drop_column("last_pull_end_at")
