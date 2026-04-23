"""aiSelfTest 包入口。"""

from __future__ import annotations

import uvicorn

from aiSelfTest.version import __version__


def main() -> None:
    """启动 aiSelfTest FastAPI 服务。"""

    uvicorn.run(
        "aiSelfTest.main:app",
        host="0.0.0.0",
        port=3001,
        reload=False,
    )


__all__ = ["__version__", "main"]
