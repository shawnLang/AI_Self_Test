"""FastAPI 应用入口。"""

from __future__ import annotations

from types import TracebackType
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import ValidationError

from aiSelfTest.api.client import router as client_router
from aiSelfTest.api.config import router as config_router
from aiSelfTest.api.dashboard import router as dashboard_router
from aiSelfTest.api.multimodal_model import router as multimodal_model_router
from aiSelfTest.api.task import task_item_router, task_router
from aiSelfTest.config import get_settings
from aiSelfTest.exceptions import (
    AppException,
    app_exception_handler,
    pydantic_validation_exception_handler,
    validation_exception_handler,
)
from aiSelfTest.version import __version__


class AppLifespan:
    """应用生命周期管理器。"""

    def __init__(self, app: FastAPI) -> None:
        """初始化生命周期管理器。"""

        self.app = app

    async def __aenter__(self) -> None:
        """应用启动时准备运行目录。"""

        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.log_dir.mkdir(parents=True, exist_ok=True)

        logger.info("启动 aiSelfTest FastAPI 应用...")
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """应用关闭时记录生命周期日志。"""

        logger.info("关闭 aiSelfTest FastAPI 应用...")


def lifespan(app: FastAPI) -> AppLifespan:
    """创建 FastAPI 生命周期上下文管理器。"""

    return AppLifespan(app)


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用。"""

    settings = get_settings()
    task_files_dir = settings.data_dir / "task_files"
    task_files_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="AI 自检平台",
        description="AI 自检平台后端 API",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ValidationError, pydantic_validation_exception_handler)
    app.add_exception_handler(AppException, app_exception_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        """为每个 HTTP 请求注入请求 ID 并记录入口/出口日志。"""

        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        with logger.contextualize(request_id=request_id):
            response = await call_next(request)
            if response.status_code != 200 and response.status_code != 304 and response.status_code != 206:
                logger.info(
                    "HTTP 请求完成: method={}, path={}, status_code={}",
                    request.method,
                    request.url.path,
                    response.status_code,
                )
        response.headers["X-Request-ID"] = request_id
        return response

    app.include_router(client_router, prefix="/api", tags=["客户端"])
    app.include_router(config_router, prefix="/api", tags=["提示词"])
    app.include_router(dashboard_router, prefix="/api", tags=["首页统计"])
    app.include_router(multimodal_model_router, prefix="/api", tags=["多模态模型"])
    app.include_router(task_router, prefix="/api", tags=["任务"])
    app.include_router(task_item_router, prefix="/api", tags=["任务项"])
    app.mount("/api/task-files", StaticFiles(directory=task_files_dir), name="task-files")
    app.mount("/assets", StaticFiles(directory=settings.static_dir / "assets"), name="assets")

    @app.get("/")
    async def root() -> FileResponse:
        """返回前端应用入口页面。"""

        return FileResponse(settings.static_dir / "index.html")

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """返回健康检查状态。"""

        return {"status": "ok"}

    return app


app = create_app()
