"""日志配置工具。"""

from __future__ import annotations

from loguru import logger

from aiSelfTest.config import get_settings


LOG_FILE_NAMES = {
    "api": "api.log",
    "worker": "worker.log",
    "beat": "beat.log",
}


def configure_deploy_file_logging(service_name: str) -> None:
    """配置部署环境文件日志，并移除 loguru 默认控制台输出。"""

    if service_name not in LOG_FILE_NAMES:
        allowed = ", ".join(sorted(LOG_FILE_NAMES))
        raise RuntimeError(f"service_name 必须是以下值之一: {allowed}")

    settings = get_settings()
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        settings.log_dir / LOG_FILE_NAMES[service_name],
        level="INFO",
        rotation="100 MB",
        retention="30 days",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )
