"""新增客户端租户信息字段。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260430_0002"
down_revision = "20260430_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """新增 client.tenant_code 与 client.tenant_name。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("client")}

    with op.batch_alter_table("client") as batch_op:
        if "tenant_code" not in columns:
            batch_op.add_column(sa.Column("tenant_code", sa.String(length=100), nullable=False, server_default=""))
        if "tenant_name" not in columns:
            batch_op.add_column(sa.Column("tenant_name", sa.String(length=200), nullable=False, server_default=""))


def downgrade() -> None:
    """回滚 client.tenant_code 与 client.tenant_name。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("client")}

    with op.batch_alter_table("client") as batch_op:
        if "tenant_name" in columns:
            batch_op.drop_column("tenant_name")
        if "tenant_code" in columns:
            batch_op.drop_column("tenant_code")
