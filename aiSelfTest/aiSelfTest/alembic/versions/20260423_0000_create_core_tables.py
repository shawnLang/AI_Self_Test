"""创建核心业务表。"""

from __future__ import annotations

from alembic import op
from sqlmodel import SQLModel

import aiSelfTest.models  # noqa: F401


revision = "20260423_0000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建当前模型声明的全部核心表。"""

    SQLModel.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """回滚核心业务表。"""

    SQLModel.metadata.drop_all(bind=op.get_bind())
