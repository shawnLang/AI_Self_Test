"""配置管理模块，集中读取运行时环境变量。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


ENV_FILE_NAME = ".env.self"


def _load_env_file(env_path: Path) -> None:
    """加载 .env.self 中尚未显式设置的环境变量。"""

    if not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env_path(name: str, default: Path) -> Path:
    """读取路径类环境变量并标准化为绝对路径。"""

    value = os.getenv(name)
    return Path(value).expanduser().resolve() if value else default


def _env_list(name: str, default: list[str]) -> list[str]:
    """读取逗号分隔的列表环境变量。"""

    value = os.getenv(name)
    if not value:
        return default

    items = [item.strip() for item in value.split(",")]
    return [item for item in items if item]


def _env_int(name: str, default: int) -> int:
    """读取整数环境变量。"""

    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是整数") from exc


def _required_env(name: str) -> str:
    """读取必填环境变量。"""

    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise RuntimeError(f"缺少必要环境变量: {name}")
    return value.strip()


def _normalize_database_url(database_url: str) -> str:
    """将 PostgreSQL URL 规整为 psycopg 驱动格式。"""

    parts = urlsplit(database_url)
    if parts.scheme == "postgresql":
        return urlunsplit(("postgresql+psycopg", parts.netloc, parts.path, parts.query, parts.fragment))
    return database_url


@dataclass(frozen=True)
class Settings:
    """集中保存服务启动所需的运行时配置。"""

    package_dir: Path
    data_dir: Path
    log_dir: Path
    static_dir: Path
    database_url: str
    redis_url: str
    request_timeout_seconds: int
    cors_origins: list[str]
    task_worker_concurrency: int
    task_time_limit_seconds: int
    task_soft_time_limit_seconds: int
    task_beat_scan_seconds: int
    task_running_stale_seconds: int
    task_queue_stale_seconds: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """构建并缓存全局配置对象。

    配置对象在一个进程内只初始化一次，既减少重复解析开销，
    也保证不同模块读取到一致的运行参数。
    """

    package_dir = Path(__file__).resolve().parent
    project_root = package_dir.parents[1]
    _load_env_file(project_root / ENV_FILE_NAME)

    data_dir = _env_path("AI_SELF_TEST_DATA_DIR", package_dir / ".aiSelfTest")
    log_dir = data_dir / "logs"
    cors_origins = _env_list(
        "AI_SELF_TEST_CORS_ORIGINS",
        ["http://localhost:5173", "http://localhost:3000"],
    )
    return Settings(
        package_dir=package_dir,
        data_dir=data_dir,
        log_dir=log_dir,
        static_dir=package_dir / "static",
        database_url=_normalize_database_url(_required_env("DATABASE_URL")),
        redis_url=_required_env("REDIS_URL"),
        request_timeout_seconds=30,
        cors_origins=cors_origins,
        task_worker_concurrency=_env_int("TASK_WORKER_CONCURRENCY", 2),
        task_time_limit_seconds=_env_int("TASK_TIME_LIMIT_SECONDS", 21600),
        task_soft_time_limit_seconds=_env_int("TASK_SOFT_TIME_LIMIT_SECONDS", 21000),
        task_beat_scan_seconds=_env_int("TASK_BEAT_SCAN_SECONDS", 60),
        task_running_stale_seconds=_env_int("TASK_RUNNING_STALE_SECONDS", 21600),
        task_queue_stale_seconds=_env_int("TASK_QUEUE_STALE_SECONDS", 600),
    )
