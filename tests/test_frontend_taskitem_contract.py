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


def test_data_query_displays_saved_filters_like_create_task() -> None:
    """任务详情页应按创建任务筛选条件完整展示并转换标签。"""

    text = read_frontend_file("components/DataQuery.tsx")

    assert "classifyOptions" in text
    assert "fileBmpOptions" in text
    assert "识别分类" in text
    assert "关键词" in text
    assert "物种名称" in text
    assert "文件格式" in text
    assert "识别类型" in text
    assert "上传类型" in text
    assert "开始时间" in text
    assert "结束时间" in text
    assert "formatClassifyList(taskFilters?.classify_list)" in text
    assert "formatMediaTypes(taskFilters?.media_types)" in text
    assert "formatIdentifySources(taskFilters?.identify_source)" in text
    assert "formatUploadTypes(taskFilters?.upload_types)" in text


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


def test_review_task_options_include_verify_stage_tasks() -> None:
    """进入核查阶段的任务应立即出现在结果复核任务下拉。"""

    api_text = read_frontend_file("api/taskItems.ts")

    assert "REVIEWABLE_TASK_STATUSES" in api_text
    assert "'核查'" in api_text
    assert "'结束'" in api_text
    assert "task.execution_status === '结束'" not in api_text


def test_review_frontend_uses_task_item_data_status_bbox_and_summary_contract() -> None:
    """复核页应按 TaskItemDataStatus 显示，并使用详情接口 bbox 绘框。"""

    api_text = read_frontend_file("api/taskItems.ts")
    review_text = read_frontend_file("components/Review.tsx")

    assert "type TaskItemBBox" in api_text
    assert "type TaskItemSourceSize" in api_text
    assert "bbox: TaskItemBBox | null" in api_text
    assert "source_size: TaskItemSourceSize | null" in api_text
    assert "sourceStatus: row.status" in api_text
    assert "submitCount: reviewRows.filter((row) => row.willSubmit).length" in api_text
    assert "excludedCount: reviewRows.filter((row) => row.decision === 'exclude').length" in api_text
    assert "willSubmit: ['默认', '新增', '修改'].includes(row.status)" in api_text
    assert "return 'add'" in api_text
    assert "if (row.sourceStatus) return row.sourceStatus" in review_text
    assert "groundingMeta: row.source_size ? { sourceSize: row.source_size } : undefined" in api_text
    assert "定位：" not in review_text
