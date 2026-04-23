"""数据库连接与会话管理。"""
from typing import Generator

import aiSelfTest.models  # noqa: F401
from loguru import logger
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel import Session, create_engine, SQLModel

from aiSelfTest.config import get_settings

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


# 异步引擎 (用于 FastAPI 异步操作) - 延迟导入
async_engine = None
AsyncSessionLocal = None


def init_async_engine():
    """初始化异步引擎 (需要安装 asyncpg)。"""
    global async_engine, AsyncSessionLocal

    try:

        async_engine = create_async_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
            # SQLite 本地文件更适合短连接，避免跨线程复用连接产生意外状态。
            poolclass=NullPool,
        )

        AsyncSessionLocal = sessionmaker(
            bind=async_engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        logger.info("异步数据库引擎初始化成功")
    except ImportError:
        logger.warning("asyncpg 未安装，异步数据库功能不可用")


def get_session() -> Generator[Session, None, None]:
    """获取同步数据库会话 (用于 Celery 任务等同步场景)。"""
    with Session(engine) as session:
        try:
            yield session
        except Exception as e:
            logger.exception("数据库会话异常")
            session.rollback()
            raise
        finally:
            session.close()


async def get_async_session():
    """获取异步数据库会话 (用于 FastAPI 路由)。"""
    if AsyncSessionLocal is None:
        raise RuntimeError("异步引擎未初始化，请先调用 init_async_engine()")

    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.exception("异步数据库会话异常")
            await session.rollback()
            raise
        finally:
            await session.close()


def init_db() -> None:
    """初始化数据库 (创建所有表)。

    注意: 生产环境应使用 Alembic 迁移，此函数仅用于开发测试。
    """

    logger.info("开始创建数据库表...")
    SQLModel.metadata.create_all(engine)
    logger.info("数据库表创建完成")
