"""Runtime configuration for the aiSelfTest FastAPI service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser().resolve() if value else default


@dataclass(frozen=True)
class Settings:
    package_dir: Path
    host: str
    port: int
    data_dir: Path
    database_path: Path
    log_dir: Path
    static_dir: Path
    request_timeout_seconds: int
    media_timeout_seconds: int
    max_body_bytes: int
    omlx_api_url: str
    omlx_api_key: str
    omlx_model: str

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path.as_posix()}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    package_dir = Path(__file__).resolve().parent
    data_dir = _env_path("AI_SELF_TEST_DATA_DIR", Path.cwd() / ".aiSelfTest")
    database_path = _env_path("AI_SELF_TEST_DB_PATH", data_dir / "database.sqlite")
    log_dir = _env_path("AI_SELF_TEST_LOG_DIR", Path.cwd() / "logs")
    return Settings(
        package_dir=package_dir,
        host=os.getenv("AI_SELF_TEST_HOST", "0.0.0.0"),
        port=_env_int("AI_SELF_TEST_PORT", 3001),
        data_dir=data_dir,
        database_path=database_path,
        log_dir=log_dir,
        static_dir=package_dir / "static",
        request_timeout_seconds=_env_int("AI_SELF_TEST_CLIENT_TIMEOUT_SECONDS", 30),
        media_timeout_seconds=_env_int("AI_SELF_TEST_MEDIA_TIMEOUT_SECONDS", 30),
        max_body_bytes=_env_int("AI_SELF_TEST_MAX_BODY_MB", 50) * 1024 * 1024,
        omlx_api_url=os.getenv("OMLX_API_URL", "http://192.168.1.116:8888/v1/chat/completions"),
        omlx_api_key=os.getenv("OMLX_API_KEY", "8888"),
        omlx_model=os.getenv("OMLX_MODEL", "gemma-4-e4b-it-8bit"),
    )
