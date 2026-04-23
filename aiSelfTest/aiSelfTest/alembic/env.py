"""Alembic 迁移环境配置。

该模块负责为 Alembic 提供元数据与数据库连接方式，
让迁移命令能够在离线和在线两种模式下工作。
"""

from __future__ import annotations

import importlib
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if "clients" not in SQLModel.metadata.tables:
    # 迁移环境执行时可能尚未显式导入模型模块，这里主动加载一次，
    # 确保 SQLModel 元数据中包含所有表定义。
    for module_name in ("aiSelfTest.db.models", "aiSelfTest.db.models"):
        try:
            importlib.import_module(module_name)
            break
        except ModuleNotFoundError:
            continue

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """在离线模式下执行迁移。

    离线模式不会实际建立数据库连接，而是基于 URL 和元数据
    生成 SQL 语句，适合导出或审查迁移脚本。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在在线模式下执行迁移。

    在线模式会建立真实数据库连接，并在事务中执行升级或回滚。
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
