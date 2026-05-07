"""应用运行时配置测试。"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlmodel import Session


def _reload_config_module():
    """重新加载配置模块，确保读取当前测试环境变量。"""

    config_module = importlib.import_module("aiSelfTest.config")
    config_module.get_settings.cache_clear()
    return importlib.reload(config_module)


def test_settings_uses_default_cors_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    """未设置环境变量时保留本地开发默认 CORS 来源。"""

    monkeypatch.delenv("AI_SELF_TEST_CORS_ORIGINS", raising=False)
    config_module = _reload_config_module()

    assert config_module.get_settings().cors_origins == [
        "http://localhost:5173",
        "http://localhost:3000",
    ]


def test_settings_reads_cors_origins_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """通过逗号分隔环境变量覆盖 CORS 来源。"""

    monkeypatch.setenv(
        "AI_SELF_TEST_CORS_ORIGINS",
        "https://admin.example.com, https://ops.example.com,,",
    )
    config_module = _reload_config_module()

    assert config_module.get_settings().cors_origins == [
        "https://admin.example.com",
        "https://ops.example.com",
    ]


def test_lifespan_runs_alembic_migrations(
    app_client: TestClient,
    db_session: Session,
) -> None:
    """应用启动时执行 Alembic 迁移并写入版本表。"""

    inspector = inspect(db_session.bind)
    assert "alembic_version" in inspector.get_table_names()

    client_columns = {
        column["name"]
        for column in inspector.get_columns("client")
    }
    assert {"expires_at", "auth_header_style", "working_url_path"}.issubset(
        client_columns
    )
    task_columns = {
        column["name"]
        for column in inspector.get_columns("task")
    }
    assert {
        "last_pull_end_at",
        "last_run_started_at",
        "skipped_count",
        "stage_started_at",
        "last_progress_at",
    }.issubset(task_columns)

    version = db_session.exec(text("select version_num from alembic_version")).one()
    assert version[0] == "20260507_0001"
