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


def test_data_query_uses_task_item_workspace_contract() -> None:
    source = _read_frontend_file("components/DataQuery.tsx")

    assert "/api/tasks/detail/" in source
    assert "/api/task-items/list" in source
    assert "/api/tasks/action-run/" in source
    assert "query-data" not in source
    assert "/execute" not in source


def test_review_api_uses_task_item_actions_not_compat_reviews() -> None:
    source = _read_frontend_file("api/review.ts")

    assert "/api/tasks/list" in source
    assert "/api/task-items/list" in source
    assert "/api/task-items/detail/" in source
    assert "/api/task-items/action-confirm" in source
    assert "/api/task-items/action-delete" in source
    assert "/api/reviews" not in source
