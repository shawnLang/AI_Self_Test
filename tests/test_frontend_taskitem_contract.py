from __future__ import annotations

from pathlib import Path


FRONTEND_SRC = Path(__file__).resolve().parents[1] / "aiSelfTestUi" / "src"


def read_frontend_file(relative_path: str) -> str:
    return (FRONTEND_SRC / relative_path).read_text(encoding="utf-8")


def test_frontend_does_not_call_review_compat_adapter_as_primary_api() -> None:
    """V1 前端应以 Task / TaskItem / TaskItem Actions 为主模型。"""

    for path in FRONTEND_SRC.rglob("*.ts*"):
        text = path.read_text(encoding="utf-8")
        assert "/api/reviews" not in text, f"{path} still calls review compat adapter"


def test_data_query_uses_task_detail_and_task_item_workspace_contract() -> None:
    """DataQuery 概念迁移为 TaskDetail / TaskItemWorkspace。"""

    text = read_frontend_file("components/DataQuery.tsx")
    api_text = read_frontend_file("api/taskItems.ts")

    assert "/api/tasks/detail/" in api_text
    assert "/api/task-items/list" in api_text
    assert "/api/tasks/action-run/" in api_text
    assert "query-data" not in text
    assert "/execute" not in text
    assert "TaskItem 工作区" in text
    assert "不再实时查询并下发旧任务数据" in text


def test_review_uses_task_item_actions_for_basic_confirmation() -> None:
    """Review 页面只做基础确认页，不再把 compat reviews 当主语义。"""

    review_text = read_frontend_file("components/Review.tsx")
    api_text = read_frontend_file("api/taskItems.ts")

    assert "../api/taskItems" in review_text
    assert "../api/review" not in review_text
    assert "/api/task-items/action-confirm" in api_text
    assert "/api/task-items/action-delete" in api_text
    assert "/api/task-items/detail/" in api_text
    assert "确认只更新 TaskItem 确认状态" in review_text
    assert "移除差异不删除源 TaskItem" in review_text
