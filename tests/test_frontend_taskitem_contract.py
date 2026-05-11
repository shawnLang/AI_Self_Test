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
    assert "模块" in text
    assert "开始时间" in text
    assert "结束时间" in text
    assert "formatClassifyList(taskFilters?.classify_list)" in text
    assert "formatMediaTypes(taskFilters?.media_types)" in text
    assert "formatIdentifySources(taskFilters?.identify_source)" in text
    assert "formatUploadTypes(taskFilters?.upload_types)" in text
    assert "formatModule(taskFilters?.module)" in text


def test_review_uses_task_item_actions_for_basic_confirmation() -> None:
    """Review 页面使用 TaskItem Actions，不再提供删除差异语义。"""

    review_text = read_frontend_file("components/Review.tsx")
    api_text = read_frontend_file("api/taskItems.ts")

    assert "../api/taskItems" in review_text
    assert "../api/review" not in review_text
    assert "/api/task-items/action-confirm" in api_text
    assert "/api/task-items/action-reject" in api_text
    assert "/api/task-items/action-submit" not in api_text
    assert "/api/task-items/action-submit-task" not in api_text
    assert "/api/tasks/action-submit/" in api_text
    assert "/api/tasks/submission-detail/" in api_text
    assert "/api/tasks/submission-current/" in api_text
    assert "/api/task-items/action-update-row" in api_text
    assert "/api/task-items/action-delete" not in api_text
    assert "/api/task-items/detail/" in api_text
    assert "确认只更新复核状态" in review_text
    assert "提交保存" in review_text
    assert "跳过" in review_text
    assert "批量跳过" in review_text
    assert "submitTaskReviewItems(Number(selectedTaskId))" in review_text
    assert "taskSubmittableIds" in review_text
    assert "submitReviewItems" not in review_text
    assert "移除差异" not in review_text
    assert "移除复核差异" not in review_text


def test_review_frontend_supports_row_editing_and_selection() -> None:
    """复核页应支持逐行编辑 llm_name/status 和显式多选批量操作。"""

    api_text = read_frontend_file("api/taskItems.ts")
    review_text = read_frontend_file("components/Review.tsx")

    assert "updateTaskItemReviewRow" in api_text
    assert "TaskItemReviewRowUpdateRequest" in api_text
    assert "task_item_data_id" in api_text
    assert "llm_name" in api_text
    assert "source_name" in api_text
    assert "原结果" in review_text
    assert "识别名称" in review_text
    assert "状态" in review_text
    assert "保存" in review_text
    assert "selectedItemIds" in review_text
    assert "全选当前可处理项" in review_text
    assert "清空选择" in review_text


def test_review_frontend_supports_confirm_state_filter() -> None:
    """复核页应支持按待复核、已确认、跳过筛选。"""

    review_text = read_frontend_file("components/Review.tsx")

    assert "type ReviewConfirmFilter" in review_text
    assert "confirmFilter" in review_text
    assert "setConfirmFilter" in review_text
    assert "待复核" in review_text
    assert "已确认" in review_text
    assert "跳过" in review_text
    assert "pendingConfirmCount" in review_text
    assert "confirmedCount" in review_text
    assert "skippedCount" in review_text


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
    assert "source_id: number | null" in api_text
    assert "det_name: string | null" in api_text
    assert "det_score: number" in api_text
    assert "llm_det_name: string | null" in api_text
    assert "sourceId: row.source_id" in api_text
    assert "detName: row.det_name" in api_text
    assert "detScore: row.det_score" in api_text
    assert "llmDetName: row.llm_det_name" in api_text
    assert "sourceStatus: row.status" in api_text
    assert "submitCount: reviewRows.filter((row) => row.willSubmit).length" in api_text
    assert "excludedCount: reviewRows.filter((row) => row.decision === 'exclude').length" in api_text
    assert "willSubmit: ['默认', '新增', '修改'].includes(row.status)" in api_text
    assert "return 'add'" in api_text
    assert "if (row.sourceStatus) return row.sourceStatus" in review_text
    assert "groundingMeta: row.source_size ? { sourceSize: row.source_size } : undefined" in api_text
    assert "定位：" not in review_text


def test_review_frontend_uses_videojson_video_overlay_contract() -> None:
    """视频绘框应由前端读取 videojson 并按 track_ids 过滤绘制。"""

    api_text = read_frontend_file("api/taskItems.ts")
    review_text = read_frontend_file("components/Review.tsx")

    assert "track_ids: string" in api_text
    assert "trackIds: row.track_ids" in api_text
    assert "resultFileUrl: detail.media.result_file_url" in api_text
    assert "type VideoVideoJsonDetection" in api_text
    assert "VideoWithVideoJsonOverlay" in review_text
    assert "fetch(item.resultFileUrl)" in review_text
    assert "trackIdSet.has(String(detection.trackId))" in review_text
    assert "video.videoWidth" in review_text
    assert "video.videoHeight" in review_text
    assert "renderVideoWithBboxOverlay(activeItem, 'w-full h-full object-contain')" in review_text
    assert "renderVideoWithBboxOverlay(previewItem, 'max-h-[78vh] max-w-full rounded-md')" in review_text


def test_review_frontend_video_overlay_uses_outer_frame_index() -> None:
    """videojson 内部 index 不是帧序，叠框应使用外层数组下标。"""

    review_text = read_frontend_file("components/Review.tsx")
    parse_text = review_text.split("function parseVideoDetection", 1)[1].split(
        "function findNearestFrameIndex",
        1,
    )[0]

    assert "const frameIndex = fallbackIndex" in parse_text
    assert "detection.index ?? fallbackIndex" not in parse_text


def test_review_frontend_video_overlay_label_matches_review_row_index() -> None:
    """视频叠框编号应对应详细结果行，而不是当前帧 detection 顺序。"""

    review_text = read_frontend_file("components/Review.tsx")
    video_overlay_text = review_text.split(
        "function VideoWithVideoJsonOverlay", 1
    )[1].split("export default function Review", 1)[0]

    assert "type RowWithDisplayIndex" in review_text
    assert "getRowsByTrackId(item.reviewRows.map((row, index) => ({ ...row, displayIndex: index + 1 })))" in video_overlay_text
    assert "{row.displayIndex}" in video_overlay_text
    assert "{index + 1}" not in video_overlay_text


def test_review_frontend_result_color_is_shared_by_overlay_and_row_list() -> None:
    """结果颜色应只表示结果对应关系，并同步用于绘框和结果列表。"""

    review_text = read_frontend_file("components/Review.tsx")

    assert "RESULT_COLOR_CLASSES" in review_text
    assert "getResultColorClass(row.displayIndex, 'border')" in review_text
    assert "getResultColorClass(row.displayIndex, 'label')" in review_text
    assert "getResultColorClass(index + 1, 'border')" in review_text
    assert "getResultColorClass(index + 1, 'label')" in review_text
    assert "getResultColorClass(index + 1, 'text')" in review_text
    assert "getStatusBorderClass(row)" in review_text
    assert "getStatusIcon(row)" in review_text
    assert "const StatusIcon = getStatusIcon(row)" in review_text


def test_review_frontend_keeps_video_overlay_between_sparse_videojson_frames() -> None:
    """videojson 帧稀疏时，视频叠框应使用最近有效帧保持连续绘制。"""

    review_text = read_frontend_file("components/Review.tsx")

    assert "frameIndexes" in review_text
    assert "findNearestFrameIndex" in review_text
    assert "findVisibleDetections" in review_text
    assert "byFrame.set(fallbackIndex, frameDetections)" in review_text
    assert "byFrame.set(detection.frameIndex, indexedDetections)" in review_text
    assert "lastFrameIndex <= frameIndex" in review_text
    assert "Math.abs(nextFrameIndex - frameIndex)" in review_text


def test_review_frontend_fullscreens_video_overlay_container() -> None:
    """视频全屏应全屏叠框容器，避免原生 video 全屏丢失 overlay。"""

    review_text = read_frontend_file("components/Review.tsx")

    assert "Maximize2" in review_text
    assert "Minimize2" in review_text
    assert "requestFullscreen()" in review_text
    assert "document.exitFullscreen()" in review_text
    assert "document.fullscreenElement === wrapperRef.current" in review_text
    assert "controlsList=\"nofullscreen\"" in review_text
    assert "aria-label={isFullscreen ? '退出全屏' : '全屏'}" in review_text


def test_review_frontend_supports_batch_re_recognition() -> None:
    """复核页应支持选中项和失败项批量重新识别。"""

    api_text = read_frontend_file("api/taskItems.ts")
    review_text = read_frontend_file("components/Review.tsx")

    assert "/api/task-items/action-re-recognize-batch" in api_text
    assert "/api/task-items/re-recognize-batch-detail/" in api_text
    assert "reRecognizeTaskItems" in review_text
    assert "getReRecognitionBatchDetail" in review_text
    assert "重新识别选中" in review_text
    assert "重新识别失败项" in review_text
    assert "selectedReRecognizableIds" in review_text
    assert "failedReRecognizableCount" in review_text
    assert "renderReRecognitionProgress()" in review_text
