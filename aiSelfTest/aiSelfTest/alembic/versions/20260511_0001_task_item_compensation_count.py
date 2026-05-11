"""新增任务项补偿次数。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260511_0001"
down_revision = "20260509_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """增加 TaskItem 补偿次数统计字段。"""

    op.add_column(
        "task_item",
        sa.Column("compensation_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("task_item", "compensation_count", server_default=None)


def downgrade() -> None:
    """回滚 TaskItem 补偿次数统计字段。"""

    op.drop_column("task_item", "compensation_count")
