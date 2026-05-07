"""task_item.file_id 改为整数。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260507_0002"
down_revision = "20260507_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """将 task_item.file_id 从字符串改为整数。"""

    bind = op.get_bind()
    invalid_rows = bind.execute(
        sa.text(
            """
            SELECT id, file_id
            FROM task_item
            WHERE file_id IS NOT NULL
              AND TRIM(CAST(file_id AS TEXT)) != ''
              AND TRIM(CAST(file_id AS TEXT)) GLOB '*[^0-9]*'
            """
        )
    ).fetchall()
    if invalid_rows:
        examples = ", ".join(f"id={row.id}, file_id={row.file_id}" for row in invalid_rows[:5])
        raise RuntimeError(f"task_item.file_id 存在非整数字符串，请先清理数据: {examples}")

    bind.execute(sa.text("UPDATE task_item SET file_id = NULL WHERE TRIM(CAST(file_id AS TEXT)) = ''"))

    with op.batch_alter_table("task_item") as batch_op:
        batch_op.alter_column(
            "file_id",
            existing_type=sa.String(length=50),
            type_=sa.Integer(),
            existing_nullable=True,
            postgresql_using="NULLIF(file_id, '')::integer",
        )


def downgrade() -> None:
    """回滚 task_item.file_id 为字符串。"""

    with op.batch_alter_table("task_item") as batch_op:
        batch_op.alter_column(
            "file_id",
            existing_type=sa.Integer(),
            type_=sa.String(length=50),
            existing_nullable=True,
        )
