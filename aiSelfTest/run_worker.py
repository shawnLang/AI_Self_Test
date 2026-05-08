"""Celery Worker 启动脚本。

该文件允许通过 ``python run_worker.py`` 的方式启动任务执行 Worker，
主要用于本地开发和 IDE 调试。
"""

from aiSelfTest.worker import main_worker


if __name__ == "__main__":
    main_worker()
