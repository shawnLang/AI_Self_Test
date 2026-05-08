"""任务 Celery 异步执行契约测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
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
) -> list[tuple[int, int, str]]:
    """拦截 Celery 投递，避免单元测试连接真实 Redis。"""

    calls: list[tuple[int, int, str]] = []

    def fake_enqueue(task_id: int, execution_id: int, celery_task_id: str) -> None:
        calls.append((task_id, execution_id, celery_task_id))

    from aiSelfTest.services.task_dispatch import TaskDispatchService

    monkeypatch.setattr(TaskDispatchService, "_enqueue_task", staticmethod(fake_enqueue))
    return calls


def test_action_run_returns_queued_execution(
    app_client: TestClient,
    db_session: Session,
    fake_celery_enqueue: list[tuple[int, int, str]],
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
    assert len(fake_celery_enqueue) == 1

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
    fake_celery_enqueue: list[tuple[int, int, str]],
) -> None:
    """同一任务已有 queued 执行实例时，重复立即执行被后端拒绝。"""

    task_id = _create_task(app_client)
    first = app_client.post(f"/api/tasks/action-run/{task_id}")
    second = app_client.post(f"/api/tasks/action-run/{task_id}")

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == 3002
    assert len(fake_celery_enqueue) == 1


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


def test_delete_running_task_is_blocked(
    app_client: TestClient,
) -> None:
    """排队或执行中的任务不能删除。"""

    task_id = _create_task(app_client)
    app_client.post(f"/api/tasks/action-run/{task_id}")

    response = app_client.delete(f"/api/tasks/delete/{task_id}")

    assert response.status_code == 409
    assert response.json()["code"] == 3002


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


def test_beat_scan_submits_due_active_tasks(
    app_client: TestClient,
    db_session: Session,
    fake_celery_enqueue: list[tuple[int, int, str]],
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
    assert len(fake_celery_enqueue) == 1


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
