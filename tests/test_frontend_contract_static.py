"""前端 Task V1 静态契约测试。"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = PROJECT_ROOT / "aiSelfTestUi" / "src"


def _read_frontend_file(relative_path: str) -> str:
    return (FRONTEND_ROOT / relative_path).read_text(encoding="utf-8")


def test_create_task_posts_canonical_config_id() -> None:
    source = _read_frontend_file("components/CreateTask.tsx")

    assert "'/api/tasks/create'" in source
    assert "config_id: parseInt(formData.configId, 10)" in source
    assert "configId: string" in source


def test_tasks_page_uses_canonical_task_routes() -> None:
    source = _read_frontend_file("components/Tasks.tsx")

    assert "'/api/tasks/list'" in source
    assert "/api/tasks/action-start/" in source
    assert "/api/tasks/action-stop/" in source
    assert "/api/tasks/action-run/" in source
    assert "/api/tasks/delete/" in source
