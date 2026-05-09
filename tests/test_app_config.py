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


def test_settings_reads_video_recognition_mode_and_frame_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """视频识别模式和整帧上限应支持环境变量配置。"""

    monkeypatch.setenv("VIDEO_RECOGNITION_MODE", "crop_per_row")
    monkeypatch.setenv("VIDEO_MAX_FULL_FRAMES_PER_VIDEO", "12")
    config_module = _reload_config_module()

    settings = config_module.get_settings()
    assert settings.video_recognition_mode == "crop_per_row"
    assert settings.video_max_full_frames_per_video == 12


def test_settings_defaults_to_full_frame_video_recognition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """视频识别默认使用整帧识别，最多 30 帧。"""

    monkeypatch.delenv("VIDEO_RECOGNITION_MODE", raising=False)
    monkeypatch.delenv("VIDEO_MAX_FULL_FRAMES_PER_VIDEO", raising=False)
    config_module = _reload_config_module()

    settings = config_module.get_settings()
    assert settings.video_recognition_mode == "full_frame"
    assert settings.video_max_full_frames_per_video == 30


def test_settings_reads_model_chat_timeout_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """大模型聊天调用超时应支持环境变量配置。"""

    monkeypatch.setenv("MODEL_CHAT_TIMEOUT_SECONDS", "180")
    config_module = _reload_config_module()

    assert config_module.get_settings().model_chat_timeout_seconds == 180


def test_settings_defaults_model_chat_timeout_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """大模型聊天调用默认超时为 300 秒。"""

    monkeypatch.delenv("MODEL_CHAT_TIMEOUT_SECONDS", raising=False)
    config_module = _reload_config_module()
    monkeypatch.setattr(config_module, "_load_env_file", lambda env_path: None)

    assert config_module.get_settings().model_chat_timeout_seconds == 300


def test_settings_reads_training_save_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """训练保存目录应支持环境变量配置。"""

    target_dir = tmp_path / "training-output"
    monkeypatch.setenv("AI_SELF_TEST_TRAINING_SAVE_DIR", str(target_dir))
    config_module = _reload_config_module()

    assert config_module.get_settings().training_save_dir == target_dir.resolve()


def test_settings_defaults_training_save_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未配置训练保存目录时，应默认放在 data_dir/training。"""

    monkeypatch.delenv("AI_SELF_TEST_TRAINING_SAVE_DIR", raising=False)
    config_module = _reload_config_module()
    monkeypatch.setattr(config_module, "_load_env_file", lambda env_path: None)

    settings = config_module.get_settings()
    assert settings.training_save_dir == settings.data_dir / "training"


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
    assert {"tenant_code", "tenant_name", "expires_at"}.issubset(client_columns)
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
        "next_run_at",
        "current_execution_id",
    }.issubset(task_columns)

    batch_columns = {
        column["name"]
        for column in inspector.get_columns("task_item_recognition_batch")
    }
    assert {
        "task_id",
        "scope",
        "task_item_ids",
        "status",
        "total_count",
        "success_count",
        "failed_count",
        "skipped_count",
        "current_task_item_id",
    }.issubset(batch_columns)

    version = db_session.exec(text("select version_num from alembic_version")).one()
    assert version[0] == "20260509_0002"
