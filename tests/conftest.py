"""测试公共夹具。"""

from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path
from typing import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "aiSelfTest"


if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


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


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """创建带独立数据目录的 FastAPI 测试客户端。"""

    temp_root = PROJECT_ROOT / ".pytest_tmp"
    temp_root.mkdir(exist_ok=True)
    test_root = temp_root / str(uuid4())
    data_dir = test_root / "data"
    monkeypatch.setenv("AI_SELF_TEST_DATA_DIR", str(data_dir))
    _reload_backend_modules()

    main_module = importlib.import_module("aiSelfTest.main")

    try:
        with TestClient(main_module.app) as client:
            yield client
    finally:
        shutil.rmtree(test_root, ignore_errors=True)


@pytest.fixture
def db_session(app_client: TestClient) -> Generator[Session, None, None]:
    """返回当前测试环境对应的数据库会话。"""

    database_module = importlib.import_module("aiSelfTest.database")
    with Session(database_module.engine) as session:
        yield session
