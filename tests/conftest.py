"""测试公共夹具。"""

from __future__ import annotations

import importlib
import re
import shutil
import sys
from pathlib import Path
from typing import Generator
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlmodel import SQLModel, Session


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "aiSelfTest"
DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_base_database_url() -> str:
    """从环境变量或 .env.self 读取 PostgreSQL 连接串。"""

    import os

    value = os.getenv("DATABASE_URL")
    if value:
        return _normalize_postgresql_driver(value.strip().strip('"').strip("'"))

    env_file = PROJECT_ROOT / ".env.self"
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "DATABASE_URL":
            return _normalize_postgresql_driver(value.strip().strip('"').strip("'"))
    raise RuntimeError("缺少 DATABASE_URL，无法创建 PostgreSQL 测试 schema")


def _normalize_postgresql_driver(database_url: str) -> str:
    """统一测试环境 PostgreSQL URL 使用 psycopg 驱动。"""

    if database_url.startswith("postgresql://"):
        return f"postgresql+psycopg://{database_url.removeprefix('postgresql://')}"
    return database_url


def _reload_backend_modules() -> None:
    """重新加载 aiSelfTest 包，确保测试使用新的环境变量。"""

    SQLModel._sa_registry.dispose()
    SQLModel.metadata.clear()
    module_names = sorted(
        (
            module_name
            for module_name in sys.modules
            if module_name == "aiSelfTest" or module_name.startswith("aiSelfTest.")
        ),
        reverse=True,
    )
    for module_name in module_names:
        sys.modules.pop(module_name, None)


def _database_url_with_schema(database_url: str, schema_name: str) -> str:
    """为 PostgreSQL URL 增加 search_path 连接参数。"""

    parts = urlsplit(database_url)
    query = f"{parts.query}&" if parts.query else ""
    query += f"options={quote(f'-csearch_path={schema_name}', safe='')}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _database_url_with_database(database_url: str, database_name: str) -> str:
    """替换 PostgreSQL URL 中的数据库名。"""

    parts = urlsplit(database_url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database_name}", "", parts.fragment))


def _extract_database_name(database_url: str) -> str:
    """从 PostgreSQL URL 中提取数据库名。"""

    database_name = urlsplit(database_url).path.lstrip("/")
    if not DATABASE_NAME_PATTERN.match(database_name):
        raise RuntimeError(f"数据库名不符合测试自动创建规则: {database_name}")
    return database_name


def _create_database_if_missing(database_url: str) -> None:
    """目标测试库不存在时，通过 postgres 维护库自动创建。"""

    database_name = _extract_database_name(database_url)
    maintenance_url = _database_url_with_database(database_url, "postgres")
    engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                {"database_name": database_name},
            ).first()
            if exists is None:
                connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        engine.dispose()


def _prepare_postgresql_schema(base_database_url: str, schema_database_url: str, schema_name: str) -> None:
    """创建当前测试独立 PostgreSQL schema 并执行基线迁移。"""

    database_module = importlib.import_module("aiSelfTest.database")
    alembic_config = database_module._build_alembic_config()
    base_engine = create_engine(base_database_url, pool_pre_ping=True)
    try:
        try:
            with base_engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
        except OperationalError:
            base_engine.dispose()
            _create_database_if_missing(base_database_url)
            base_engine = create_engine(base_database_url, pool_pre_ping=True)
            with base_engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    finally:
        base_engine.dispose()

    alembic_config.set_main_option("sqlalchemy.url", schema_database_url.replace("%", "%%"))
    command.upgrade(alembic_config, "head")


def _drop_postgresql_schema(base_database_url: str, schema_name: str) -> None:
    """删除当前测试独立 PostgreSQL schema。"""

    engine = create_engine(base_database_url, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
    engine.dispose()


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """创建带独立数据目录的 FastAPI 测试客户端。"""

    temp_root = PROJECT_ROOT / ".pytest_tmp"
    temp_root.mkdir(exist_ok=True)
    test_root = temp_root / str(uuid4())
    data_dir = test_root / "data"
    schema_name = f"test_{uuid4().hex}"
    base_database_url = _load_base_database_url()
    schema_database_url = _database_url_with_schema(base_database_url, schema_name)
    monkeypatch.setenv("AI_SELF_TEST_DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", schema_database_url)
    _reload_backend_modules()
    _prepare_postgresql_schema(base_database_url, schema_database_url, schema_name)

    main_module = importlib.import_module("aiSelfTest.main")

    try:
        with TestClient(main_module.app) as client:
            yield client
    finally:
        _drop_postgresql_schema(base_database_url, schema_name)
        shutil.rmtree(test_root, ignore_errors=True)


@pytest.fixture
def db_session(app_client: TestClient) -> Generator[Session, None, None]:
    """返回当前测试环境对应的数据库会话。"""

    database_module = importlib.import_module("aiSelfTest.database")
    with Session(database_module.engine) as session:
        yield session
