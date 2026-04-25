"""更新客户端认证缓存字段。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260425_0001"
down_revision = "20260423_0001"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    """升级客户端认证缓存字段。"""

    columns = _columns("client")
    with op.batch_alter_table("client") as batch_op:
        if "expires_in" in columns and "expires_at" not in columns:
            batch_op.alter_column("expires_in", new_column_name="expires_at")
        elif "expires_at" not in columns:
            batch_op.add_column(sa.Column("expires_at", sa.Integer(), nullable=True))

        if "auth_header_style" not in columns:
            batch_op.add_column(sa.Column("auth_header_style", sa.String(length=20), nullable=True))

        if "working_url_path" not in columns:
            batch_op.add_column(sa.Column("working_url_path", sa.String(length=200), nullable=True))

    op.execute(
        "UPDATE client SET expires_at = CAST(expires_at / 1000 AS INTEGER) "
        "WHERE expires_at > 100000000000"
    )


def downgrade() -> None:
    """回滚客户端认证缓存字段。"""

    columns = _columns("client")
    with op.batch_alter_table("client") as batch_op:
        if "working_url_path" in columns:
            batch_op.drop_column("working_url_path")
        if "auth_header_style" in columns:
            batch_op.drop_column("auth_header_style")
        if "expires_at" in columns and "expires_in" not in columns:
            batch_op.alter_column("expires_at", new_column_name="expires_in")
