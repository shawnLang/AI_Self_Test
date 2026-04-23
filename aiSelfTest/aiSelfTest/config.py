"""配置管理模块，使用 pydantic-settings 管理环境变量。"""
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _env_path(name: str, default: Path) -> Path:
    """读取路径类环境变量并标准化为绝对路径。"""

    value = os.getenv(name)
    return Path(value).expanduser().resolve() if value else default


@dataclass(frozen=True)
class Settings:
    """集中保存服务启动所需的运行时配置。"""

    package_dir: Path
    data_dir: Path
    database_path: Path
    log_dir: Path
    static_dir: Path
    request_timeout_seconds: int

    @property
    def database_url(self) -> str:
        """将本地 SQLite 文件路径转换为 SQLAlchemy 连接串。"""

        return f"sqlite:///{self.database_path.as_posix()}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """构建并缓存全局配置对象。

    配置对象在一个进程内只初始化一次，既减少重复解析开销，
    也保证不同模块读取到一致的运行参数。
    """

    package_dir = Path(__file__).resolve().parent
    data_dir = _env_path("AI_SELF_TEST_DATA_DIR", package_dir / ".aiSelfTest")
    database_path = data_dir / "database.sqlite"
    log_dir = data_dir / "logs"
    return Settings(
        package_dir=package_dir,
        data_dir=data_dir,
        database_path=database_path,
        log_dir=log_dir,
        static_dir=package_dir / "static",
        request_timeout_seconds=30,
    )
