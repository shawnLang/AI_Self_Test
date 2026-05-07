"""数据库连接与会话管理。"""
from typing import Generator

from alembic import command
from alembic.config import Config
from loguru import logger
from sqlalchemy import event
from sqlalchemy.pool import NullPool
from sqlmodel import Session, create_engine

import aiSelfTest.models  # noqa: F401
from aiSelfTest.config import get_settings
from aiSelfTest.exceptions import AppException

settings = get_settings()

# 同步引擎 (用于 Alembic 迁移和同步操作)
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    # SQLite 本地文件更适合短连接，避免跨线程复用连接产生意外状态。
    poolclass=NullPool,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
    """在每次连接建立后设置 SQLite 运行参数。"""

    cursor = dbapi_connection.cursor()
    # WAL 提升并发读写能力；busy_timeout 降低锁冲突失败概率；
    # foreign_keys 保证外键约束在 SQLite 下生效。
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_session() -> Generator[Session, None, None]:
    """获取同步数据库会话 (用于 FastAPI 同步路由)。"""
    with Session(engine) as session:
        try:
            yield session
        except AppException:
            session.rollback()
            raise
        except Exception:
            logger.exception("数据库会话异常")
            session.rollback()
            raise
        finally:
            session.close()


def run_migrations() -> None:
    """执行 Alembic 数据库迁移。"""

    logger.info("开始执行数据库迁移...")
    alembic_config = _build_alembic_config()
    command.upgrade(alembic_config, "head")
    logger.info("数据库迁移完成")


def _build_alembic_config() -> Config:
    """构建绑定当前运行时数据库地址的 Alembic 配置。"""

    config_path = settings.package_dir / "alembic.ini"
    alembic_config = Config(config_path.as_posix())
    alembic_config.set_main_option(
        "script_location",
        (settings.package_dir / "alembic").as_posix(),
    )
    alembic_config.set_main_option("sqlalchemy.url", settings.database_url)
    return alembic_config
