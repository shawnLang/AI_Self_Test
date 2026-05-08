"""数据库连接与会话管理。"""
from typing import Generator

from alembic import command
from alembic.config import Config
from loguru import logger
from sqlmodel import Session, create_engine

import aiSelfTest.models  # noqa: F401
from aiSelfTest.config import get_settings
from aiSelfTest.exceptions import AppException

settings = get_settings()

# 同步引擎 (用于 Alembic 迁移和同步操作)
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)


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
    alembic_config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    return alembic_config
