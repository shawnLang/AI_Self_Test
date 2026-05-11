"""任务 Celery 异步执行契约测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select


def _unwrap_success(response_json: dict[str, Any]) -> Any:
    assert response_json["code"] == 0
    assert response_json["message"] == "success"
    return response_json["data"]


@pytest.fixture(autouse=True)
def fake_celery_enqueue(
    app_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, list[tuple[Any, ...]]]:
    """拦截 Celery 投递，避免单元测试连接真实 Redis。"""

    calls: dict[str, list[tuple[Any, ...]]] = {
        "task_execution": [],
        "task_submission": [],
        "task_compensation": [],
    }

    def fake_enqueue(task_id: int, execution_id: int, celery_task_id: str) -> None:
        calls["task_execution"].append((task_id, execution_id, celery_task_id))

    def fake_submission_enqueue(submission_id: int, celery_task_id: str) -> None:
        calls["task_submission"].append((submission_id, celery_task_id))

    def fake_compensation_enqueue(task_id: int, execution_id: int, celery_task_id: str) -> None:
        calls["task_compensation"].append((task_id, execution_id, celery_task_id))

    from aiSelfTest.services.task_dispatch import TaskDispatchService
    from aiSelfTest.services.task_item_compensation import TaskItemCompensationService
    from aiSelfTest.services.task_submission_job import TaskSubmissionJobService

    monkeypatch.setattr(TaskDispatchService, "_enqueue_task", staticmethod(fake_enqueue))
    monkeypatch.setattr(TaskItemCompensationService, "_enqueue_compensation", staticmethod(fake_compensation_enqueue))
    monkeypatch.setattr(TaskSubmissionJobService, "_enqueue_submission", staticmethod(fake_submission_enqueue))
    return calls


def test_action_run_returns_queued_execution(
    app_client: TestClient,
    db_session: Session,
    fake_celery_enqueue: dict[str, list[tuple[Any, ...]]],
) -> None:
    """立即执行只入队并快速返回，不同步跑执行主干。"""

    task_id = _create_task(app_client)

    response = app_client.post(f"/api/tasks/action-run/{task_id}")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["id"] == task_id
    assert data["current_execution_id"] is not None
    assert data["current_execution_status"] == "queued"
    assert data["display_status"] == "排队中"
    assert len(fake_celery_enqueue["task_execution"]) == 1

    task_model, execution_model = _import_task_models()
    task = db_session.get(task_model, task_id)
    execution = db_session.get(execution_model, data["current_execution_id"])
    assert task is not None
    assert task.started_at is None
    assert task.current_execution_id == execution.id
    assert execution.status == "queued"
    assert execution.trigger_type == "manual"
    assert execution.celery_task_id == f"task-execution-{execution.id}"


def test_duplicate_action_run_returns_resource_busy(
    app_client: TestClient,
    fake_celery_enqueue: dict[str, list[tuple[Any, ...]]],
) -> None:
    """同一任务已有 queued 执行实例时，重复立即执行被后端拒绝。"""

    task_id = _create_task(app_client)
    first = app_client.post(f"/api/tasks/action-run/{task_id}")
    second = app_client.post(f"/api/tasks/action-run/{task_id}")

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == 3002
    assert len(fake_celery_enqueue["task_execution"]) == 1


def test_task_list_exposes_current_execution_fields(
    app_client: TestClient,
) -> None:
    """任务列表返回当前执行实例字段和展示状态。"""

    task_id = _create_task(app_client)
    app_client.post(f"/api/tasks/action-run/{task_id}")

    response = app_client.get("/api/tasks/list")

    assert response.status_code == 200
    items = _unwrap_success(response.json())["items"]
    row = next(item for item in items if item["id"] == task_id)
    assert row["current_execution_status"] == "queued"
    assert row["display_status"] == "排队中"
    assert row["compensation_limited_count"] == 0


def test_task_list_exposes_compensation_limited_count(
    app_client: TestClient,
    db_session: Session,
) -> None:
    """任务列表应返回达到补偿上限且仍失败的任务项数量，供前端控制恢复入口。"""

    from aiSelfTest.models.task import TaskItem, TaskItemStatus
    from aiSelfTest.services.task_item_compensation import TASK_ITEM_COMPENSATION_MAX_ATTEMPTS

    task_id = _create_task(app_client)
    limited_item = TaskItem(
        task_id=task_id,
        name="image-limited-list.jpg",
        device_name="device-1",
        file_num="file-1",
        file_extension="jpg",
        file_url="image-limited-list.jpg",
        file_id=9671,
        file_fid="fid-9671",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status=TaskItemStatus.FAILED.value,
        down_state=False,
        down_error="download failed",
        compensation_count=TASK_ITEM_COMPENSATION_MAX_ATTEMPTS,
        updated_at=datetime.now() - timedelta(seconds=600),
    )
    retryable_item = TaskItem(
        task_id=task_id,
        name="image-retryable-list.jpg",
        device_name="device-1",
        file_num="file-2",
        file_extension="jpg",
        file_url="image-retryable-list.jpg",
        file_id=9672,
        file_fid="fid-9672",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status=TaskItemStatus.FAILED.value,
        down_state=False,
        down_error="download failed",
        compensation_count=TASK_ITEM_COMPENSATION_MAX_ATTEMPTS - 1,
        updated_at=datetime.now() - timedelta(seconds=600),
    )
    db_session.add(limited_item)
    db_session.add(retryable_item)
    db_session.commit()

    response = app_client.get("/api/tasks/list")

    assert response.status_code == 200
    items = _unwrap_success(response.json())["items"]
    row = next(item for item in items if item["id"] == task_id)
    assert row["compensation_limited_count"] == 1


def test_delete_running_task_is_blocked(
    app_client: TestClient,
) -> None:
    """排队或执行中的任务不能删除。"""

    task_id = _create_task(app_client)
    app_client.post(f"/api/tasks/action-run/{task_id}")

    response = app_client.delete(f"/api/tasks/delete/{task_id}")

    assert response.status_code == 409
    assert response.json()["code"] == 3002


def test_delete_task_cleans_re_recognition_batches(
    app_client: TestClient,
    db_session: Session,
) -> None:
    """删除任务时应先清理后台关联记录，避免外键阻止删除。"""

    task_id = _create_task(app_client)
    task_model, task_item_model, task_item_data_model, batch_model, submission_model = _import_task_delete_models()
    task_item = task_item_model(
        task_id=task_id,
        name="image-1.jpg",
        device_name="device-1",
        file_num="file-1",
        file_extension="jpg",
        file_url="https://example.com/image-1.jpg",
        file_id=7001,
        file_fid="fid-7001",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status="已创建",
    )
    db_session.add(task_item)
    db_session.commit()
    db_session.refresh(task_item)
    task_item_data = task_item_data_model(
        task_item_id=task_item.id,
        name="白鹭",
        score=0.9,
        track_ids="1",
        sp_amount=1,
    )
    batch = batch_model(
        task_id=task_id,
        scope="selected",
        task_item_ids=str(task_item.id),
        status="success",
        total_count=1,
    )
    submission = submission_model(
        task_id=task_id,
        status="success",
        total_count=1,
        success_count=1,
    )
    db_session.add(task_item_data)
    db_session.add(batch)
    db_session.add(submission)
    db_session.commit()

    response = app_client.delete(f"/api/tasks/delete/{task_id}")

    assert response.status_code == 200
    assert db_session.get(task_model, task_id) is None
    assert db_session.exec(select(task_item_model).where(task_item_model.task_id == task_id)).all() == []
    assert db_session.exec(select(task_item_data_model)).all() == []
    assert db_session.exec(select(batch_model).where(batch_model.task_id == task_id)).all() == []
    assert db_session.exec(select(submission_model).where(submission_model.task_id == task_id)).all() == []


def test_worker_executes_queued_record_successfully(
    app_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Worker 成功执行 queued 记录后写入 success 并清空当前执行 ID。"""

    task_id = _create_task(app_client)
    execution_id = _unwrap_success(app_client.post(f"/api/tasks/action-run/{task_id}").json())[
        "current_execution_id"
    ]

    import aiSelfTest.worker as worker_module

    monkeypatch.setattr(worker_module, "run_task_execution", lambda session, task_id: None)

    worker_module.execute_task.run(task_id, execution_id)

    task_model, execution_model = _import_task_models()
    task = db_session.get(task_model, task_id)
    execution = db_session.get(execution_model, execution_id)
    assert task.current_execution_id is None
    assert execution.status == "success"
    assert execution.started_at is not None
    assert execution.finished_at is not None


def test_worker_marks_execution_failed_on_error(
    app_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Worker 执行异常时写入 failed、error 和任务失败聚合状态。"""

    task_id = _create_task(app_client)
    execution_id = _unwrap_success(app_client.post(f"/api/tasks/action-run/{task_id}").json())[
        "current_execution_id"
    ]

    import aiSelfTest.worker as worker_module

    def raise_error(session: Session, task_id: int) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(worker_module, "run_task_execution", raise_error)

    with pytest.raises(RuntimeError):
        worker_module.execute_task.run(task_id, execution_id)

    task_model, execution_model = _import_task_models()
    task = db_session.get(task_model, task_id)
    execution = db_session.get(execution_model, execution_id)
    assert task.current_execution_id is None
    assert task.execution_status == "失败"
    assert execution.status == "failed"
    assert execution.error == "boom"


def test_submission_worker_processes_confirmed_task_items(
    app_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """提交保存 Worker 只处理已确认可提交项，并写入提交进度。"""

    task_id = _create_task(app_client)
    task_model, task_item_model, _, _, submission_model = _import_task_delete_models()
    confirmed_item = task_item_model(
        task_id=task_id,
        name="image-confirmed.jpg",
        device_name="device-1",
        file_num="file-1",
        file_extension="jpg",
        file_url="https://example.com/image-confirmed.jpg",
        file_id=7101,
        file_fid="fid-confirmed",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status="已确认",
        confirm_state="已确认",
        remote_state="待提交",
        train_state="待保存",
    )
    pending_item = task_item_model(
        task_id=task_id,
        name="image-pending.jpg",
        device_name="device-1",
        file_num="file-2",
        file_extension="jpg",
        file_url="https://example.com/image-pending.jpg",
        file_id=7102,
        file_fid="fid-pending",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status="待复核",
        confirm_state="待确认",
        remote_state="待提交",
        train_state="待保存",
    )
    task = db_session.get(task_model, task_id)
    task.execution_status = "核查"
    db_session.add(task)
    db_session.add(confirmed_item)
    db_session.add(pending_item)
    db_session.commit()
    db_session.refresh(confirmed_item)
    db_session.refresh(pending_item)

    submission = submission_model(task_id=task_id, status="queued")
    db_session.add(submission)
    db_session.commit()
    db_session.refresh(submission)

    from aiSelfTest.services.task_submission import TaskSubmissionService

    processed_ids: list[int] = []

    def fake_submit(self: TaskSubmissionService, task_item: Any) -> None:
        processed_ids.append(task_item.id)
        task_item.status = "已完成"
        task_item.remote_state = "已提交"
        task_item.train_state = "已保存"
        self.session.add(task_item)
        self.session.commit()

    monkeypatch.setattr(TaskSubmissionService, "submit_task_item_outputs", fake_submit)

    import aiSelfTest.worker as worker_module

    worker_module.execute_task_submission.run(submission.id)

    db_session.expire_all()
    stored_submission = db_session.get(submission_model, submission.id)
    stored_confirmed = db_session.get(task_item_model, confirmed_item.id)
    stored_pending = db_session.get(task_item_model, pending_item.id)
    stored_task = db_session.get(task_model, task_id)
    assert processed_ids == [confirmed_item.id]
    assert stored_submission.status == "success"
    assert stored_submission.total_count == 1
    assert stored_submission.success_count == 1
    assert stored_submission.failed_count == 0
    assert stored_submission.finished_at is not None
    assert stored_confirmed.status == "已完成"
    assert stored_confirmed.remote_state == "已提交"
    assert stored_pending.status == "待复核"
    assert stored_task.execution_status == "核查"


def test_submission_worker_records_partial_failure(
    app_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """提交保存 Worker 单项失败时记录失败数和错误摘要，不中断整批任务。"""

    task_id = _create_task(app_client)
    _, task_item_model, _, _, submission_model = _import_task_delete_models()
    first_item = task_item_model(
        task_id=task_id,
        name="image-ok.jpg",
        device_name="device-1",
        file_num="file-1",
        file_extension="jpg",
        file_url="https://example.com/image-ok.jpg",
        file_id=7201,
        file_fid="fid-ok",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status="已确认",
        confirm_state="已确认",
        remote_state="待提交",
        train_state="待保存",
    )
    second_item = task_item_model(
        task_id=task_id,
        name="image-fail.jpg",
        device_name="device-1",
        file_num="file-2",
        file_extension="jpg",
        file_url="https://example.com/image-fail.jpg",
        file_id=7202,
        file_fid="fid-fail",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status="已确认",
        confirm_state="已确认",
        remote_state="待提交",
        train_state="待保存",
    )
    db_session.add(first_item)
    db_session.add(second_item)
    db_session.commit()
    db_session.refresh(first_item)
    db_session.refresh(second_item)

    submission = submission_model(task_id=task_id, status="queued")
    db_session.add(submission)
    db_session.commit()
    db_session.refresh(submission)

    from aiSelfTest.services.task_submission import TaskSubmissionService

    def fake_submit(self: TaskSubmissionService, task_item: Any) -> None:
        if task_item.id == second_item.id:
            raise RuntimeError("submit failed")
        task_item.status = "已完成"
        task_item.remote_state = "已提交"
        task_item.train_state = "已保存"
        self.session.add(task_item)
        self.session.commit()

    monkeypatch.setattr(TaskSubmissionService, "submit_task_item_outputs", fake_submit)

    import aiSelfTest.worker as worker_module

    worker_module.execute_task_submission.run(submission.id)

    db_session.expire_all()
    stored_submission = db_session.get(submission_model, submission.id)
    stored_first = db_session.get(task_item_model, first_item.id)
    stored_second = db_session.get(task_item_model, second_item.id)
    assert stored_submission.status == "partial_failed"
    assert stored_submission.total_count == 2
    assert stored_submission.success_count == 1
    assert stored_submission.failed_count == 1
    assert f"TaskItem {second_item.id}: submit failed" in stored_submission.error_summary
    assert stored_first.status == "已完成"
    assert stored_second.remote_state == "待提交"


def test_beat_scan_submits_due_active_tasks(
    app_client: TestClient,
    db_session: Session,
    fake_celery_enqueue: dict[str, list[tuple[Any, ...]]],
) -> None:
    """Beat 扫描 active 且到期的任务并提交 schedule 执行。"""

    task_id = _create_task(app_client)
    task_model, execution_model = _import_task_models()
    task = db_session.get(task_model, task_id)
    task.active = True
    task.next_run_at = datetime.now() - timedelta(seconds=1)
    db_session.add(task)
    db_session.commit()

    from aiSelfTest.worker import scan_scheduled_tasks

    submitted = scan_scheduled_tasks.run()

    execution = db_session.exec(select(execution_model).where(execution_model.task_id == task_id)).one()
    db_session.refresh(task)
    assert submitted == 1
    assert execution.trigger_type == "schedule"
    assert execution.status == "queued"
    assert task.next_run_at is not None
    assert task.next_run_at > datetime.now()
    assert len(fake_celery_enqueue["task_execution"]) == 1


def test_task_execution_detail_rows_store_source_id_and_detection_fields(
    app_client: TestClient,
    db_session: Session,
) -> None:
    """上游详情行 ID、detName 和 detScore 应落库到 TaskItemData。"""

    task_id = _create_task(app_client)
    from aiSelfTest.services.task_execution import SourceTaskItemDetail, SourceTaskItemRecord, TaskExecutionRunner

    class FakeSource:
        def fetch_task_item_detail(self, session, task, task_item, source_record):
            return SourceTaskItemDetail(
                result_file_data="result-file-id",
                record_data=[
                    {
                        "id": 8801,
                        "name": "白鹭",
                        "score": 0.91,
                        "detName": "鸟",
                        "detScore": 0.81,
                        "trackIds": "1",
                        "spAmount": 1,
                        "minx": 1,
                        "miny": 2,
                        "maxx": 3,
                        "maxy": 4,
                    }
                ],
            )

    runner = TaskExecutionRunner(db_session, task_id)
    runner.source = FakeSource()
    source_record = SourceTaskItemRecord(
        name="image-1.jpg",
        file_fid="fid-8801",
        file_url="https://example.com/image-1.jpg",
        file_bmp=1,
        file_id=8801,
    )
    inserted_items, _ = runner._insert_new_task_items([source_record])
    task_item, _ = inserted_items[0]

    inserted_count = runner._insert_task_item_data_rows(task_item, source_record)

    from aiSelfTest.models.task import TaskItemData

    row = db_session.exec(select(TaskItemData).where(TaskItemData.task_item_id == task_item.id)).one()
    db_session.refresh(task_item)
    assert inserted_count == 1
    assert task_item.result_file_data == "result-file-id"
    assert row.source_id == 8801
    assert row.det_name == "鸟"
    assert row.det_score == 0.81
    assert row.llm_det_name is None


def test_file_download_error_contains_full_upstream_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """下载 HTTP 异常应带出完整上游 URL，便于定位拼接问题。"""

    from aiSelfTest.exceptions import AppException
    from aiSelfTest.services.task_execution import RequestsTaskFileDownloader

    class FakeResponse:
        status_code = 400
        text = "bad request"

    requested_urls: list[str] = []

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        requested_urls.append(url)
        return FakeResponse()

    monkeypatch.setattr("aiSelfTest.services.task_execution.requests.get", fake_get)
    url = "https://example.com/weed/task-file.jpg"

    with pytest.raises(AppException) as exc_info:
        RequestsTaskFileDownloader()._download_url(url, Path("/tmp/task-file.jpg"))

    assert requested_urls == [url, url, url]
    assert url in exc_info.value.message
    assert "HTTP 400" in exc_info.value.message


def test_download_stage_keeps_task_item_error_and_continues(
    app_client: TestClient,
    db_session: Session,
) -> None:
    """下载阶段单项失败应保留错误并继续处理后续项。"""

    from aiSelfTest.exceptions import AppException
    from aiSelfTest.models.task import TaskItem, TaskItemStatus
    from aiSelfTest.services.task_execution import SourceTaskItemRecord, TaskExecutionRunner

    task_id = _create_task(app_client)
    failed_item = TaskItem(
        task_id=task_id,
        name="image-fail.jpg",
        device_name="device-1",
        file_num="file-1",
        file_extension="jpg",
        file_url="image-fail.jpg",
        file_id=9301,
        file_fid="fid-9301",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status="详情已加载",
    )
    success_item = TaskItem(
        task_id=task_id,
        name="image-ok.jpg",
        device_name="device-1",
        file_num="file-2",
        file_extension="jpg",
        file_url="image-ok.jpg",
        file_id=9302,
        file_fid="fid-9302",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status="详情已加载",
    )
    db_session.add(failed_item)
    db_session.add(success_item)
    db_session.commit()
    db_session.refresh(failed_item)
    db_session.refresh(success_item)

    class FailingDownloader:
        def download(self, **kwargs: Any) -> None:
            task_item = kwargs["task_item"]
            if task_item.id == success_item.id:
                from aiSelfTest.services.task_execution import TaskDownloadResult

                return TaskDownloadResult(file_path="/tmp/image-ok.jpg")
            raise AppException(
                code=3001,
                message="文件下载失败: HTTP 400, url=https://example.com/weed/image-fail.jpg",
                status_code=502,
            )

    runner = TaskExecutionRunner(db_session, task_id, downloader=FailingDownloader())
    runner._source_record_from_task_item = lambda _task_item: SourceTaskItemRecord(
        name="image-fail.jpg",
        file_fid="fid-9301",
        file_url="image-fail.jpg",
        file_bmp=1,
        file_id=9301,
    )

    runner._run_download_stage()

    db_session.refresh(failed_item)
    db_session.refresh(success_item)
    assert failed_item.status == TaskItemStatus.FAILED.value
    assert failed_item.down_state is False
    assert "HTTP 400" in failed_item.down_error
    assert "https://example.com/weed/image-fail.jpg" in failed_item.down_error
    assert success_item.status == TaskItemStatus.DOWNLOADED.value
    assert success_item.down_state is True
    assert runner.download_failed_count == 1
    assert runner.download_success_count == 1


def test_llm_stage_single_item_failure_does_not_stop_batch(
    app_client: TestClient,
    db_session: Session,
) -> None:
    """大模型阶段单项失败不应阻断后续任务项识别。"""

    from aiSelfTest.exceptions import AppException
    from aiSelfTest.models.task import TaskItem, TaskItemLlmState, TaskItemStatus
    from aiSelfTest.services.task_execution import TaskExecutionRunner, TaskItemRecognitionResult
    from aiSelfTest.services.task_steps.llm_result import LlmDetectionResult

    task_id = _create_task(app_client)
    first = TaskItem(
        task_id=task_id,
        name="image-fail.jpg",
        device_name="device-1",
        file_num="file-1",
        file_extension="jpg",
        file_url="image-fail.jpg",
        file_id=9401,
        file_fid="fid-9401",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status=TaskItemStatus.DOWNLOADED.value,
        down_state=True,
        file_path="/tmp/image-fail.jpg",
    )
    second = TaskItem(
        task_id=task_id,
        name="image-ok.jpg",
        device_name="device-1",
        file_num="file-2",
        file_extension="jpg",
        file_url="image-ok.jpg",
        file_id=9402,
        file_fid="fid-9402",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status=TaskItemStatus.DOWNLOADED.value,
        down_state=True,
        file_path="/tmp/image-ok.jpg",
    )
    db_session.add(first)
    db_session.add(second)
    db_session.commit()
    db_session.refresh(first)
    db_session.refresh(second)

    class FakeRecognizer:
        def recognize(self, **kwargs: Any) -> TaskItemRecognitionResult:
            task_item = kwargs["task_item"]
            if task_item.id == first.id:
                raise AppException(code=3001, message="模型接口失败", status_code=502)
            return TaskItemRecognitionResult(image_result=LlmDetectionResult(width=100, height=100, data=[]))

    runner = TaskExecutionRunner(db_session, task_id, recognizer=FakeRecognizer())

    runner._run_llm_stage()

    db_session.refresh(first)
    db_session.refresh(second)
    assert first.llm_state == TaskItemLlmState.FAIL.value
    assert first.status == TaskItemStatus.FAILED.value
    assert "模型接口失败" in first.llm_error
    assert second.llm_state == TaskItemLlmState.SUCCESS.value
    assert runner.llm_failed_count == 1
    assert runner.llm_success_count == 1


def test_task_execution_returns_fail_when_all_items_failed(
    app_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """整批没有可复核项时任务聚合状态为失败，Worker 执行记录也应失败。"""

    from aiSelfTest.models.task import TaskExecution, TaskExecutionRecordStatus, TaskItem, TaskItemStatus

    task_id = _create_task(app_client)
    task_item = TaskItem(
        task_id=task_id,
        name="image-fail.jpg",
        device_name="device-1",
        file_num="file-1",
        file_extension="jpg",
        file_url="image-fail.jpg",
        file_id=9501,
        file_fid="fid-9501",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status=TaskItemStatus.DATA_LOADED.value,
    )
    execution = TaskExecution(
        task_id=task_id,
        trigger_type="manual",
        status=TaskExecutionRecordStatus.QUEUED.value,
    )
    db_session.add(task_item)
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)

    class FailingDownloader:
        def download(self, **kwargs: Any) -> None:
            raise RuntimeError("download boom")

    import aiSelfTest.worker as worker_module
    from aiSelfTest.services import task_execution

    original_runner = task_execution.TaskExecutionRunner

    class RunnerWithFailingDownloader(original_runner):
        def __init__(self, session, task_id, downloader=None, recognizer=None, now=None):
            super().__init__(session, task_id, downloader=FailingDownloader(), recognizer=recognizer, now=now)

        def _run_create_stage(self) -> None:
            self.task.total_count = self._count_task_items()
            self.session.add(self.task)
            self.session.commit()

        def _run_data_load_stage(self) -> None:
            return None

    monkeypatch.setattr(
        worker_module,
        "run_task_execution",
        lambda session, task_id: RunnerWithFailingDownloader(session, task_id).run(),
    )

    worker_module.execute_task.run(task_id, execution.id)

    db_session.refresh(execution)
    db_session.refresh(task_item)
    assert execution.status == TaskExecutionRecordStatus.FAILED.value
    assert execution.error == "下载失败任务项数量=1"
    assert task_item.down_state is False
    assert "download boom" in task_item.down_error


def test_compensation_scan_enqueues_failed_task_items(
    app_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """补偿扫描应为存在失败项的任务创建 repair 执行记录。"""

    from datetime import datetime, timedelta

    from aiSelfTest.models.task import Task, TaskExecution, TaskItem, TaskItemStatus
    from aiSelfTest.services.task_item_compensation import TaskItemCompensationService

    task_id = _create_task(app_client)
    task_item = TaskItem(
        task_id=task_id,
        name="image-fail.jpg",
        device_name="device-1",
        file_num="file-1",
        file_extension="jpg",
        file_url="image-fail.jpg",
        file_id=9601,
        file_fid="fid-9601",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status=TaskItemStatus.FAILED.value,
        down_state=False,
        down_error="download failed",
        updated_at=datetime.now() - timedelta(seconds=600),
    )
    db_session.add(task_item)
    db_session.commit()

    calls: list[tuple[int, int, str]] = []

    def fake_enqueue(task_id: int, execution_id: int, celery_task_id: str) -> None:
        calls.append((task_id, execution_id, celery_task_id))

    monkeypatch.setattr(TaskItemCompensationService, "_enqueue_compensation", staticmethod(fake_enqueue))

    submitted = TaskItemCompensationService(db_session).scan_and_enqueue()

    task = db_session.get(Task, task_id)
    execution = db_session.exec(select(TaskExecution).where(TaskExecution.task_id == task_id)).one()
    assert submitted == 1
    assert execution.trigger_type == "repair"
    assert execution.status == "queued"
    assert task.current_execution_id == execution.id
    assert calls == [(task_id, execution.id, f"task-item-compensation-{execution.id}")]


def test_compensation_scan_skips_items_reaching_max_attempts(
    app_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """达到最大补偿次数的失败任务项不应再次自动补偿。"""

    from datetime import datetime, timedelta

    from aiSelfTest.models.task import TaskExecution, TaskItem, TaskItemStatus
    from aiSelfTest.services.task_item_compensation import (
        TASK_ITEM_COMPENSATION_MAX_ATTEMPTS,
        TaskItemCompensationService,
    )

    task_id = _create_task(app_client)
    task_item = TaskItem(
        task_id=task_id,
        name="image-max-attempts.jpg",
        device_name="device-1",
        file_num="file-1",
        file_extension="jpg",
        file_url="image-max-attempts.jpg",
        file_id=9651,
        file_fid="fid-9651",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status=TaskItemStatus.FAILED.value,
        down_state=False,
        down_error="download failed",
        compensation_count=TASK_ITEM_COMPENSATION_MAX_ATTEMPTS,
        updated_at=datetime.now() - timedelta(seconds=600),
    )
    db_session.add(task_item)
    db_session.commit()

    calls: list[tuple[int, int, str]] = []

    def fake_enqueue(task_id: int, execution_id: int, celery_task_id: str) -> None:
        calls.append((task_id, execution_id, celery_task_id))

    monkeypatch.setattr(TaskItemCompensationService, "_enqueue_compensation", staticmethod(fake_enqueue))

    submitted = TaskItemCompensationService(db_session).scan_and_enqueue()

    executions = db_session.exec(select(TaskExecution).where(TaskExecution.task_id == task_id)).all()
    assert submitted == 0
    assert executions == []
    assert calls == []


def test_reset_task_compensation_requires_limited_failed_items(
    app_client: TestClient,
) -> None:
    """任务没有达到补偿上限的失败项时，补偿恢复接口不可使用。"""

    task_id = _create_task(app_client)

    response = app_client.post(f"/api/tasks/action-reset-compensation/{task_id}")

    assert response.status_code == 400
    assert response.json()["code"] == 1001
    assert "没有达到补偿上限" in response.json()["message"]


def test_reset_task_compensation_resets_count_and_enqueues_repair(
    app_client: TestClient,
    db_session: Session,
    fake_celery_enqueue: dict[str, list[tuple[Any, ...]]],
) -> None:
    """补偿恢复接口应重置达到上限的失败项，并立即投递 repair 执行。"""

    from datetime import datetime, timedelta

    from aiSelfTest.models.task import TaskExecution, TaskItem, TaskItemStatus
    from aiSelfTest.services.task_item_compensation import TASK_ITEM_COMPENSATION_MAX_ATTEMPTS

    task_id = _create_task(app_client)
    limited_item = TaskItem(
        task_id=task_id,
        name="image-limited.jpg",
        device_name="device-1",
        file_num="file-1",
        file_extension="jpg",
        file_url="image-limited.jpg",
        file_id=9661,
        file_fid="fid-9661",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status=TaskItemStatus.FAILED.value,
        down_state=False,
        down_error="download failed",
        compensation_count=TASK_ITEM_COMPENSATION_MAX_ATTEMPTS,
        updated_at=datetime.now() - timedelta(seconds=600),
    )
    normal_failed_item = TaskItem(
        task_id=task_id,
        name="image-normal-failed.jpg",
        device_name="device-1",
        file_num="file-2",
        file_extension="jpg",
        file_url="image-normal-failed.jpg",
        file_id=9662,
        file_fid="fid-9662",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status=TaskItemStatus.FAILED.value,
        down_state=False,
        down_error="download failed",
        compensation_count=1,
        updated_at=datetime.now() - timedelta(seconds=600),
    )
    db_session.add(limited_item)
    db_session.add(normal_failed_item)
    db_session.commit()
    db_session.refresh(limited_item)
    db_session.refresh(normal_failed_item)

    response = app_client.post(f"/api/tasks/action-reset-compensation/{task_id}")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    execution = db_session.get(TaskExecution, data["execution_id"])
    db_session.refresh(limited_item)
    db_session.refresh(normal_failed_item)
    assert data["task_id"] == task_id
    assert data["reset_count"] == 1
    assert data["execution_status"] == "queued"
    assert execution.trigger_type == "repair"
    assert limited_item.compensation_count == 0
    assert normal_failed_item.compensation_count == 1
    assert fake_celery_enqueue["task_execution"] == []
    assert fake_celery_enqueue["task_compensation"] == [
        (task_id, execution.id, f"task-item-compensation-{execution.id}")
    ]
    assert len(fake_celery_enqueue["task_submission"]) == 0


def test_compensation_execute_recovers_download_and_llm_failure(
    app_client: TestClient,
    db_session: Session,
) -> None:
    """补偿执行应重新下载失败项，并重新识别已下载但识别失败项。"""

    from datetime import datetime, timedelta

    from aiSelfTest.models.task import (
        Task,
        TaskExecution,
        TaskExecutionRecordStatus,
        TaskItem,
        TaskItemLlmState,
        TaskItemStatus,
    )
    from aiSelfTest.services.task_execution import TaskDownloadResult, TaskItemRecognitionResult
    from aiSelfTest.services.task_steps.llm_result import LlmDetectionResult
    from aiSelfTest.services.task_item_compensation import TaskItemCompensationService

    task_id = _create_task(app_client)
    old_time = datetime.now() - timedelta(seconds=600)
    download_failed = TaskItem(
        task_id=task_id,
        name="image-download-fail.jpg",
        device_name="device-1",
        file_num="file-1",
        file_extension="jpg",
        file_url="image-download-fail.jpg",
        file_id=9701,
        file_fid="fid-9701",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status=TaskItemStatus.FAILED.value,
        down_state=False,
        down_error="download failed",
        updated_at=old_time,
    )
    llm_failed = TaskItem(
        task_id=task_id,
        name="image-llm-fail.jpg",
        device_name="device-1",
        file_num="file-2",
        file_extension="jpg",
        file_url="image-llm-fail.jpg",
        file_id=9702,
        file_fid="fid-9702",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status=TaskItemStatus.FAILED.value,
        down_state=True,
        file_path="/tmp/image-llm-fail.jpg",
        llm_state=TaskItemLlmState.FAIL.value,
        llm_error="llm failed",
        updated_at=old_time,
    )
    execution = TaskExecution(
        task_id=task_id,
        trigger_type="repair",
        status=TaskExecutionRecordStatus.QUEUED.value,
    )
    db_session.add(download_failed)
    db_session.add(llm_failed)
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(download_failed)
    db_session.refresh(llm_failed)
    db_session.refresh(execution)
    task = db_session.get(Task, task_id)
    task.current_execution_id = execution.id
    db_session.add(task)
    db_session.commit()

    class FakeDownloader:
        def download(self, **kwargs: Any) -> TaskDownloadResult:
            task_item = kwargs["task_item"]
            return TaskDownloadResult(file_path=f"/tmp/{task_item.file_id}.jpg")

    class FakeRecognizer:
        def recognize(self, **kwargs: Any) -> TaskItemRecognitionResult:
            return TaskItemRecognitionResult(image_result=LlmDetectionResult(width=100, height=100, data=[]))

    service = TaskItemCompensationService(db_session)
    runner = service

    from aiSelfTest.services import task_item_compensation

    original_runner = task_item_compensation.TaskExecutionRunner

    class RunnerWithFakes(original_runner):
        def __init__(self, session, task_id, downloader=None, recognizer=None, now=None):
            super().__init__(session, task_id, downloader=FakeDownloader(), recognizer=FakeRecognizer(), now=now)

    task_item_compensation.TaskExecutionRunner = RunnerWithFakes
    try:
        result = runner.execute(task_id, execution.id)
    finally:
        task_item_compensation.TaskExecutionRunner = original_runner

    db_session.refresh(download_failed)
    db_session.refresh(llm_failed)
    db_session.refresh(execution)
    db_session.refresh(task)
    assert result.total_count == 2
    assert result.success_count == 2
    assert result.failed_count == 0
    assert execution.status == TaskExecutionRecordStatus.SUCCESS.value
    assert task.current_execution_id is None
    assert task.execution_status == "核查"
    assert download_failed.down_state is True
    assert download_failed.llm_state == TaskItemLlmState.SUCCESS.value
    assert llm_failed.llm_state == TaskItemLlmState.SUCCESS.value
    assert download_failed.compensation_count == 1
    assert llm_failed.compensation_count == 1


def test_compensation_execute_stops_after_max_failed_attempts(
    app_client: TestClient,
    db_session: Session,
) -> None:
    """失败任务项达到最大补偿次数后，后续扫描不再投递补偿。"""

    from datetime import datetime, timedelta

    from aiSelfTest.models.task import Task, TaskExecution, TaskExecutionRecordStatus, TaskItem, TaskItemStatus
    from aiSelfTest.services.task_item_compensation import (
        TASK_ITEM_COMPENSATION_MAX_ATTEMPTS,
        TaskItemCompensationService,
    )

    task_id = _create_task(app_client)
    task_item = TaskItem(
        task_id=task_id,
        name="image-still-fail.jpg",
        device_name="device-1",
        file_num="file-1",
        file_extension="jpg",
        file_url="image-still-fail.jpg",
        file_id=9751,
        file_fid="fid-9751",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status=TaskItemStatus.FAILED.value,
        down_state=False,
        down_error="download failed",
        compensation_count=TASK_ITEM_COMPENSATION_MAX_ATTEMPTS - 1,
        updated_at=datetime.now() - timedelta(seconds=600),
    )
    execution = TaskExecution(
        task_id=task_id,
        trigger_type="repair",
        status=TaskExecutionRecordStatus.QUEUED.value,
    )
    db_session.add(task_item)
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(task_item)
    db_session.refresh(execution)
    task = db_session.get(Task, task_id)
    task.current_execution_id = execution.id
    db_session.add(task)
    db_session.commit()

    class FailingDownloader:
        def download(self, **kwargs: Any) -> None:
            raise RuntimeError("still failed")

    from aiSelfTest.services import task_item_compensation

    original_runner = task_item_compensation.TaskExecutionRunner

    class RunnerWithFailingDownloader(original_runner):
        def __init__(self, session, task_id, downloader=None, recognizer=None, now=None):
            super().__init__(session, task_id, downloader=FailingDownloader(), recognizer=recognizer, now=now)

    task_item_compensation.TaskExecutionRunner = RunnerWithFailingDownloader
    try:
        result = TaskItemCompensationService(db_session).execute(task_id, execution.id)
    finally:
        task_item_compensation.TaskExecutionRunner = original_runner

    db_session.refresh(task_item)
    db_session.refresh(execution)
    db_session.refresh(task)
    assert result.failed_count == 1
    assert task_item.compensation_count == TASK_ITEM_COMPENSATION_MAX_ATTEMPTS
    assert task_item.down_state is False
    assert "still failed" in task_item.down_error
    assert execution.status == TaskExecutionRecordStatus.FAILED.value
    assert "达到补偿上限任务项数量=1" in task.last_error

    task_item.updated_at = datetime.now() - timedelta(seconds=600)
    db_session.add(task_item)
    db_session.commit()
    assert TaskItemCompensationService(db_session).scan_and_enqueue() == 0


def _create_task(app_client: TestClient) -> int:
    client_id = _unwrap_success(
        app_client.post(
            "/api/clients/create",
            json={
                "name": "Celery 项目",
                "apiUrl": "https://example.com",
                "account": "task-admin",
                "password": "secret-123",
                "status": "启用",
            },
        ).json()
    )["id"]
    config_id = _unwrap_success(
        app_client.post(
            "/api/configs/create",
            json={
                "name": "Celery 提示词",
                "remark": "Celery 测试用提示词",
                "text": "请返回识别结果。",
                "format": 0,
            },
        ).json()
    )["id"]
    return _unwrap_success(
        app_client.post(
            "/api/tasks/create",
            json={
                "name": "Celery 异步任务",
                "client_id": client_id,
                "config_id": config_id,
                "interval_hours": 1,
                "execution_mode": "manual",
                "auto_execute": False,
                "filters": {
                    "classify_list": [1],
                    "keyword": "",
                    "sp_name": "",
                    "start_at": "",
                    "end_at": "",
                    "media_types": ["image"],
                    "upload_types": [],
                    "identify_source": [],
                    "module": "camera",
                },
            },
        ).json()
    )["id"]


def _import_task_models():
    from aiSelfTest.models.task import Task, TaskExecution

    return Task, TaskExecution


def _import_task_delete_models():
    from aiSelfTest.models.task import Task, TaskItem, TaskItemData, TaskItemRecognitionBatch, TaskSubmission

    return Task, TaskItem, TaskItemData, TaskItemRecognitionBatch, TaskSubmission
