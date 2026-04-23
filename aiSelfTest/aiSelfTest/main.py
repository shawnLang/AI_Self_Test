"""FastAPI 应用入口。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import ValidationError


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    # 启动时
    logger.info("启动 FastAPI 应用...")

    # yield

    # 关闭时
    logger.info("关闭 FastAPI 应用...")


# 创建 FastAPI 应用
app = FastAPI(
    title="AI自检平台",
    description="AI自检平台后端 API",
    version="1.0.0",
    lifespan=lifespan
)

# 注册全局异常处理器
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(ValidationError, pydantic_validation_exception_handler)

# CORS 中间件（开发环境）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],  # 前端开发服务器地址
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(roles.router, prefix="/api/v1")
app.include_router(species.router, prefix="/api/v1")
app.include_router(project.router, prefix="/api/v1")
app.include_router(dataset.router, prefix="/api/v1")
app.include_router(training.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api/v1")


@app.get("/")
async def root():
    """根路径。"""
    return {
        "message": "AI自检平台 API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """健康检查。"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "aiSelfTest.main:app",
        host="0.0.0.0",
        port=3001,
        reload=True
    )
