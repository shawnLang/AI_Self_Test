"""Celery Worker 与 Beat 部署启动入口。"""

from __future__ import annotations

import argparse
from typing import Sequence

from aiSelfTest.logging import configure_deploy_file_logging
from aiSelfTest.worker import main_beat, main_worker


def main(argv: Sequence[str] | None = None) -> int:
    """根据服务角色配置文件日志并启动 Celery 进程。"""

    parser = argparse.ArgumentParser(description="Start aiSelfTest Celery services.")
    parser.add_argument("service", choices=("worker", "beat"))
    args = parser.parse_args(argv)

    configure_deploy_file_logging(args.service)
    if args.service == "worker":
        main_worker()
        return 0

    main_beat()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
