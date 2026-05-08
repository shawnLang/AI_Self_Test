"""Celery Beat 启动脚本。

该文件允许通过 ``python run_beat.py`` 的方式启动定时调度进程，
主要用于本地开发和 IDE 调试。
"""

from aiSelfTest.worker import main_beat


if __name__ == "__main__":
    main_beat()
