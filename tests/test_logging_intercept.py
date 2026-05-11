"""标准 logging 接管测试。"""

from __future__ import annotations

import logging
from pathlib import Path

from loguru import logger


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_standard_logging_is_forwarded_to_loguru_sink() -> None:
    """标准 logging 记录应被转发到 loguru sink。"""

    from aiSelfTest.logging import install_std_logging_intercept

    messages: list[str] = []
    sink_id = logger.add(messages.append, format="{level}|{name}|{message}")
    try:
        install_std_logging_intercept(logger_names=["test.aiSelfTest"], level=logging.INFO)
        standard_logger = logging.getLogger("test.aiSelfTest")
        standard_logger.info("standard logging event")
    finally:
        logger.remove(sink_id)

    assert any(message.startswith("INFO|") and "standard logging event" in message for message in messages)
    assert logging.getLogger("test.aiSelfTest").handlers == []
    assert logging.getLogger("test.aiSelfTest").propagate is True


def test_uvicorn_run_disables_default_log_config() -> None:
    """API 启动应禁用 Uvicorn 默认日志配置，避免重复输出。"""

    source = (PROJECT_ROOT / "aiSelfTest" / "aiSelfTest" / "server.py").read_text(encoding="utf-8")

    assert "configure_deploy_logging(\"api\")" in source
    assert "log_config=None" in source


def test_celery_logging_hijack_is_disabled() -> None:
    """Celery 不应覆盖 root logger，并应保留 stdout 重定向。"""

    source = (PROJECT_ROOT / "aiSelfTest" / "aiSelfTest" / "celery_app.py").read_text(encoding="utf-8")
    worker_source = (PROJECT_ROOT / "aiSelfTest" / "aiSelfTest" / "worker.py").read_text(encoding="utf-8")

    assert "worker_hijack_root_logger=False" in source
    assert "worker_redirect_stdouts=True" in source
    assert "worker_redirect_stdouts_level=\"INFO\"" in source
    assert "configure_deploy_logging(\"worker\")" in worker_source
    assert "configure_deploy_logging(\"beat\")" in worker_source
