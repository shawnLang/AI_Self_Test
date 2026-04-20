"""FastAPI application factory and static frontend hosting."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from aiSelfTest.config import Settings, get_settings
from aiSelfTest.db.session import configure_engine
from aiSelfTest.logging import log_error, log_event, setup_logging
from aiSelfTest.migrations import run_migrations


def _cache_headers(path: Path) -> dict[str, str]:
    if path.name == "index.html":
        return {"Cache-Control": "no-cache"}
    if any(part.startswith("assets") for part in path.parts):
        return {"Cache-Control": "public, max-age=31536000, immutable"}
    return {"Cache-Control": "public, max-age=3600"}


def _safe_static_path(static_dir: Path, requested_path: str) -> Path | None:
    candidate = (static_dir / requested_path.lstrip("/")).resolve()
    try:
        candidate.relative_to(static_dir.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            configure_engine(settings)
            run_migrations(settings)
            from .services.tasks import restore_interrupted_tasks
            from .services.multimodal import ensure_default_model_registered

            restore_interrupted_tasks()
            ensure_default_model_registered()
            log_event("startup", "aiSelfTest started", host=settings.host, port=settings.port)
        except Exception as exc:
            log_error("startup", "startup failed", error=str(exc))
            raise
        yield
        from .services.tasks import cancel_running_tasks

        cancel_running_tasks()
        log_event("shutdown", "aiSelfTest stopped")

    app = FastAPI(title="aiSelfTest", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def legacy_http_exception_handler(_request: Request, exc: HTTPException):
        if isinstance(exc.detail, dict):
            return JSONResponse(exc.detail, status_code=exc.status_code)
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next: Callable):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > settings.max_body_bytes:
            return JSONResponse({"error": "请求体超过 50MB 限制"}, status_code=413)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            log_error(
                "exception",
                "unhandled request exception",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                error=str(exc),
            )
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        log_event(
            "request_out",
            "request completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    from .api.clients import router as clients_router
    from .api.dashboard import router as dashboard_router
    from .api.multimodal_models import router as models_router
    from .api.reviews import router as reviews_router
    from .api.tasks import router as tasks_router

    app.include_router(clients_router)
    app.include_router(models_router)
    app.include_router(tasks_router)
    app.include_router(reviews_router)
    app.include_router(dashboard_router)

    @app.get("/{full_path:path}", include_in_schema=False)
    def static_frontend(full_path: str = ""):
        if full_path.startswith("api/") or full_path == "api":
            return JSONResponse({"error": "Not found"}, status_code=404)

        static_dir = settings.static_dir
        requested = full_path or "index.html"
        file_path = _safe_static_path(static_dir, requested)
        if file_path is None:
            file_path = _safe_static_path(static_dir, "index.html")
        if file_path is None:
            return JSONResponse({"error": "前端静态资源不存在，请先构建前端。"}, status_code=503)
        return FileResponse(file_path, headers=_cache_headers(file_path))

    return app
