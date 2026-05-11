"""Celery Worker 与 Beat 部署启动入口。"""

from __future__ import annotations

import argparse
from typing import Sequence

from aiSelfTest.logging import configure_deploy_logging
from aiSelfTest.worker import start_beat_without_logging_config, start_worker_without_logging_config


def main(argv: Sequence[str] | None = None) -> int:
    """根据服务角色配置文件日志并启动 Celery 进程。"""

    parser = argparse.ArgumentParser(description="Start aiSelfTest Celery services.")
    parser.add_argument("service", choices=("worker", "beat"))
    args = parser.parse_args(argv)

    configure_deploy_logging(args.service)
    if args.service == "worker":
        start_worker_without_logging_config()
        return 0

    start_beat_without_logging_config()
    return 0


def main_worker() -> int:
    """启动 Celery Worker 部署进程。"""

    return main(["worker"])


def main_beat() -> int:
    """启动 Celery Beat 部署进程。"""

    return main(["beat"])


if __name__ == "__main__":
    raise SystemExit(main())
