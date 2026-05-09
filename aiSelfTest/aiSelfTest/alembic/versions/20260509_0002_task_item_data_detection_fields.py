"""新增任务项明细检测分类字段。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260509_0002"
down_revision = "20260509_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """为任务项明细增加上游 ID 与检测分类字段。"""

    op.add_column("task_item_data", sa.Column("source_id", sa.Integer(), nullable=True))
    op.add_column("task_item_data", sa.Column("det_name", sa.String(length=100), nullable=True))
    op.add_column("task_item_data", sa.Column("det_score", sa.Float(), nullable=False, server_default="0"))
    op.add_column("task_item_data", sa.Column("llm_det_name", sa.String(length=100), nullable=True))
    op.alter_column("task_item_data", "det_score", server_default=None)


def downgrade() -> None:
    """回滚任务项明细检测分类字段。"""

    op.drop_column("task_item_data", "llm_det_name")
    op.drop_column("task_item_data", "det_score")
    op.drop_column("task_item_data", "det_name")
    op.drop_column("task_item_data", "source_id")
