"""新增 task_item.file_id 唯一检查字段。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260430_0001"
down_revision = "20260425_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """新增 file_id 并改用 task_id + file_id 唯一约束。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("task_item")}
    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("task_item")
    }

    with op.batch_alter_table("task_item") as batch_op:
        if "file_id" not in columns:
            batch_op.add_column(sa.Column("file_id", sa.String(length=50), nullable=True))
        if "uq_task_item_task_id_file_fid" in unique_constraints:
            batch_op.drop_constraint("uq_task_item_task_id_file_fid", type_="unique")
        if "uq_task_item_task_id_file_id" not in unique_constraints:
            batch_op.create_unique_constraint(
                "uq_task_item_task_id_file_id",
                ["task_id", "file_id"],
            )


def downgrade() -> None:
    """回滚 file_id 唯一检查字段。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("task_item")}
    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("task_item")
    }

    with op.batch_alter_table("task_item") as batch_op:
        if "uq_task_item_task_id_file_id" in unique_constraints:
            batch_op.drop_constraint("uq_task_item_task_id_file_id", type_="unique")
        if "uq_task_item_task_id_file_fid" not in unique_constraints:
            batch_op.create_unique_constraint(
                "uq_task_item_task_id_file_fid",
                ["task_id", "file_fid"],
            )
        if "file_id" in columns:
            batch_op.drop_column("file_id")
