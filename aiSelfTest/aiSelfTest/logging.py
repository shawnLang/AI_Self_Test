"""日志配置工具。"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterable

from loguru import logger

from aiSelfTest.config import get_settings


INTERCEPT_LOGGER_NAMES = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "alembic",
    "celery",
    "celery.app.trace",
    "celery.worker",
    "celery.beat",
)

LOG_FILE_NAMES = {
    "api": "api.log",
    "worker": "worker.log",
    "beat": "beat.log",
}


class InterceptHandler(logging.Handler):
    """将标准 logging 记录转发到 loguru。"""

    def emit(self, record: logging.LogRecord) -> None:
        """转发单条标准日志记录。"""

        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame is not None and (
            frame.f_code.co_filename == logging.__file__ or frame.f_code.co_filename == __file__
        ):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


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


def configure_deploy_logging(service_name: str, logger_names: Iterable[str] = INTERCEPT_LOGGER_NAMES) -> None:
    """配置部署文件日志，并接管标准 logging 输出。"""

    configure_deploy_file_logging(service_name)
    install_std_logging_intercept(logger_names=logger_names)


def install_std_logging_intercept(
    *,
    logger_names: Iterable[str] = INTERCEPT_LOGGER_NAMES,
    level: int = logging.INFO,
) -> None:
    """接管标准 logging，将指定 logger 转发到 loguru。"""

    intercept_handler = InterceptHandler()
    intercept_handler.setLevel(level)

    root_logger = logging.getLogger()
    root_logger.handlers = [intercept_handler]
    root_logger.setLevel(level)

    for logger_name in logger_names:
        standard_logger = logging.getLogger(logger_name)
        standard_logger.handlers = []
        standard_logger.propagate = True
        standard_logger.setLevel(level)


def configure_development_logging(logger_names: Iterable[str] = INTERCEPT_LOGGER_NAMES) -> None:
    """配置开发环境控制台日志，并接管标准 logging 输出。"""

    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        backtrace=True,
        diagnose=False,
    )
    install_std_logging_intercept(logger_names=logger_names)
