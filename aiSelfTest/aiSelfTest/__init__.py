"""aiSelfTest 包入口。"""

from __future__ import annotations

from aiSelfTest.version import __version__


__all__ = ["__version__", "main"]


def __getattr__(name: str):
    """按需导入运行入口，避免包导入阶段加载运行时配置。"""

    if name == "main":
        from aiSelfTest.server import main

        return main
    raise AttributeError(f"module 'aiSelfTest' has no attribute {name!r}")
