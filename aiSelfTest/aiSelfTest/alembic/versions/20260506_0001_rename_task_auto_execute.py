"""任务自动执行字段改名。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260506_0001"
down_revision = "20260430_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """把 auto_confirm 改为 auto_execute。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    task_columns = {column["name"] for column in inspector.get_columns("task")}

    with op.batch_alter_table("task") as batch_op:
        if "auto_execute" not in task_columns and "auto_confirm" in task_columns:
            batch_op.alter_column("auto_confirm", new_column_name="auto_execute")
        elif "auto_execute" not in task_columns:
            batch_op.add_column(sa.Column("auto_execute", sa.Boolean(), nullable=False, server_default="0"))


def downgrade() -> None:
    """回滚 auto_execute 字段名称。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    task_columns = {column["name"] for column in inspector.get_columns("task")}

    with op.batch_alter_table("task") as batch_op:
        if "auto_confirm" not in task_columns and "auto_execute" in task_columns:
            batch_op.alter_column("auto_execute", new_column_name="auto_confirm")
        elif "auto_confirm" not in task_columns:
            batch_op.add_column(sa.Column("auto_confirm", sa.Boolean(), nullable=False, server_default="0"))
