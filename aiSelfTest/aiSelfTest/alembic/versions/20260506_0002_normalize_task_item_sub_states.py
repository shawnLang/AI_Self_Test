"""规范 TaskItem 子状态字段。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260506_0002"
down_revision = "20260506_0001"
branch_labels = None
depends_on = None


TASK_ITEM_STATE_COLUMNS = (
    "llm_state",
    "confirm_state",
    "remote_state",
    "train_state",
)

STATE_VALUE_MAPPINGS = {
    "llm_state": {
        None: "待识别",
        "pending": "待识别",
        "running": "识别中",
        "success": "识别完成",
        "fail": "识别失败",
        "failed": "识别失败",
    },
    "confirm_state": {
        None: "待确认",
        "pending": "待确认",
        "confirmed": "已确认",
        "manual_confirmed": "已确认",
        "auto_confirmed": "已确认",
        "skipped": "已跳过",
        "rejected": "已跳过",
    },
    "remote_state": {
        None: "待提交",
        "pending": "待提交",
        "success": "已提交",
        "fail": "提交失败",
        "failed": "提交失败",
    },
    "train_state": {
        None: "待保存",
        "pending": "待保存",
        "saved": "已保存",
        "success": "已保存",
        "fail": "保存失败",
        "failed": "保存失败",
    },
}

STATE_DEFAULT_VALUES = {
    "llm_state": "待识别",
    "confirm_state": "待确认",
    "remote_state": "待提交",
    "train_state": "待保存",
}


def upgrade() -> None:
    """把 TaskItem 子状态字段规范为中文非空默认值。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("task_item")}

    for column in TASK_ITEM_STATE_COLUMNS:
        if column in columns:
            _normalize_state_values(column)

    with op.batch_alter_table("task_item") as batch_op:
        for column in TASK_ITEM_STATE_COLUMNS:
            if column in columns:
                batch_op.alter_column(
                    column,
                    existing_type=sa.String(length=20),
                    nullable=False,
                    server_default=STATE_DEFAULT_VALUES[column],
                )


def downgrade() -> None:
    """回滚 TaskItem 子状态字段的非空默认约束。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("task_item")}

    with op.batch_alter_table("task_item") as batch_op:
        for column in TASK_ITEM_STATE_COLUMNS:
            if column in columns:
                batch_op.alter_column(
                    column,
                    existing_type=sa.String(length=20),
                    nullable=True,
                    server_default=None,
                )


def _normalize_state_values(column: str) -> None:
    """把旧英文状态值转换为中文状态值。"""

    mapping = STATE_VALUE_MAPPINGS[column]
    null_value = mapping[None]
    op.execute(sa.text(f"UPDATE task_item SET {column} = :new_value WHERE {column} IS NULL").bindparams(
        new_value=null_value,
    ))
    for old_value, new_value in mapping.items():
        if old_value is None:
            continue
        op.execute(sa.text(f"UPDATE task_item SET {column} = :new_value WHERE {column} = :old_value").bindparams(
            new_value=new_value,
            old_value=old_value,
        ))
