"""前端 Task V1 静态契约测试。"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = PROJECT_ROOT / "aiSelfTestUi" / "src"


def _read_frontend_file(relative_path: str) -> str:
    return (FRONTEND_ROOT / relative_path).read_text(encoding="utf-8")


def test_create_task_posts_canonical_config_id() -> None:
    source = _read_frontend_file("components/CreateTask.tsx")
    filters_source = _read_frontend_file("constants/taskFilters.ts")

    assert "'/api/tasks/create'" in source
    assert "config_id: parseInt(formData.configId, 10)" in source
    assert "configId: string" in source
    assert "moduleOptions" in source
    assert "module: formData.filters.module" in source
    assert "module: 'camera'" in filters_source
    assert "{ value: 'camera', label: '红外相机' }" in filters_source
    assert "{ value: 'lure', label: '喂鸟器' }" in filters_source
    assert "{ value: 'video', label: '摄像头' }" in filters_source


def test_tasks_page_uses_canonical_task_routes() -> None:
    source = _read_frontend_file("components/Tasks.tsx")

    assert "'/api/tasks/list'" in source
    assert "/api/tasks/action-start/" in source
    assert "/api/tasks/action-stop/" in source
    assert "/api/tasks/action-run/" in source
    assert "/api/tasks/delete/" in source
    assert "任务数据" in source
    assert "已下载文件" in source
    assert "不可恢复" in source


def test_task_card_action_buttons_do_not_wrap_or_confuse_run_with_schedule() -> None:
    source = _read_frontend_file("components/Tasks.tsx")
    api_source = _read_frontend_file("api/taskItems.ts")

    assert "whitespace-nowrap" in source
    assert "启用调度" in source
    assert "暂停调度" in source
    assert "立即执行" in source
    assert "title=\"启用自动调度\"" in source
    assert "title=\"立即执行\"" in source
    assert "skipped_count: number" in source
    assert "skipped_count: number" in api_source
    assert "task.skipped_count" in source
    assert "estimated_remaining_seconds: number | null" in source
    assert "estimated_remaining_seconds: number | null" in api_source
    assert "runningExecutionStatuses" in source
    assert "task.execution_status === '创建' && Boolean(task.started_at)" in source
    assert "formatRemainingTime(task.estimated_remaining_seconds, isExecuting)" in source
    assert "filters: TaskFiltersPayload" in source
    assert "模块" in source
    assert "formatModule(task.filters?.module)" in source
    assert "计算中" in source
    assert "暂未估算" in source
    assert "约 ${totalSeconds} 秒" in source
    assert "约 ${minutes} 分 ${remainingSeconds} 秒" in source
