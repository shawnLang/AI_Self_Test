"""API 服务启动入口。"""

from __future__ import annotations

import os

import uvicorn
from loguru import logger

from aiSelfTest.database import run_migrations
from aiSelfTest.logging import configure_deploy_logging


def main(*, configure_file_logging: bool = True) -> None:
    """先执行数据库迁移，再启动 FastAPI API 服务。"""

    if configure_file_logging:
        configure_deploy_logging("api")
    host = _env_str("AI_SELF_TEST_API_HOST", "0.0.0.0")
    port = _env_int("AI_SELF_TEST_API_PORT", 3001)
    workers = _env_int("AI_SELF_TEST_API_WORKERS", 1)

    logger.info("启动 API 服务前执行数据库迁移...")
    run_migrations()
    logger.info("数据库迁移完成，启动 API 服务: host={}, port={}, workers={}", host, port, workers)
    uvicorn.run(
        "aiSelfTest.main:app",
        host=host,
        port=port,
        workers=workers,
        reload=False,
        log_config=None,
    )


def _env_str(name: str, default: str) -> str:
    """读取字符串环境变量。"""

    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _env_int(name: str, default: int) -> int:
    """读取整数环境变量。"""

    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是整数") from exc


if __name__ == "__main__":
    main()
