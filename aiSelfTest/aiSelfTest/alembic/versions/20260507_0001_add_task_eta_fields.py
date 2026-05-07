"""补充任务预计剩余时间计算字段。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260507_0001"
down_revision = "20260506_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """为任务表补充阶段计时字段。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    task_columns = {column["name"] for column in inspector.get_columns("task")}

    with op.batch_alter_table("task") as batch_op:
        if "stage_started_at" not in task_columns:
            batch_op.add_column(sa.Column("stage_started_at", sa.DateTime(), nullable=True))
        if "last_progress_at" not in task_columns:
            batch_op.add_column(sa.Column("last_progress_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """回滚任务阶段计时字段。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    task_columns = {column["name"] for column in inspector.get_columns("task")}

    with op.batch_alter_table("task") as batch_op:
        if "last_progress_at" in task_columns:
            batch_op.drop_column("last_progress_at")
        if "stage_started_at" in task_columns:
            batch_op.drop_column("stage_started_at")
