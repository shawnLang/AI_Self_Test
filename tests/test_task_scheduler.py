"""Task 单进程调度器契约测试。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session


class FakeScheduler:
    """记录 APScheduler 调用的轻量 fake。"""

    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.running = False

    def add_job(self, func: Any, trigger: str, **kwargs: Any) -> None:
        self.jobs[kwargs["id"]] = {"func": func, "trigger": trigger, **kwargs}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    def remove_job(self, job_id: str) -> None:
        self.jobs.pop(job_id, None)

    def start(self) -> None:
        self.running = True

    def shutdown(self, wait: bool = True) -> None:
        self.running = False


def test_task_scheduler_restores_active_tasks_and_removes_inactive_jobs(
    app_client: TestClient,
    db_session: Session,
) -> None:
    task_id = _create_task(app_client)
    task_model = _import_task_model()
    task = db_session.get(task_model, task_id)
    task.active = True
    db_session.add(task)
    db_session.commit()

    fake_scheduler = FakeScheduler()
    task_scheduler_module = _import_task_scheduler_module()
    scheduler = task_scheduler_module.TaskScheduler(scheduler=fake_scheduler)

    scheduler.restore_active_tasks(db_session)
    assert f"task_{task_id}" in fake_scheduler.jobs
    assert fake_scheduler.jobs[f"task_{task_id}"]["hours"] == 1

    task.active = False
    db_session.add(task)
    db_session.commit()

    scheduler.sync_task(task_id)
    assert f"task_{task_id}" not in fake_scheduler.jobs


def test_recover_zombie_tasks_marks_stale_running_task_failed(
    app_client: TestClient,
    db_session: Session,
) -> None:
    task_id = _create_task(app_client)
    task_model = _import_task_model()
    task_scheduler_module = _import_task_scheduler_module()
    task = db_session.get(task_model, task_id)
    task.active = True
    task.execution_status = "下载"
    task.last_run_started_at = datetime(2026, 4, 25, 1, 0, 0)
    db_session.add(task)
    db_session.commit()

    recovered = task_scheduler_module.recover_zombie_tasks(
        db_session,
        now=datetime(2026, 4, 25, 10, 0, 0),
        stale_after_hours=6,
    )

    stored_task = db_session.get(task_model, task_id)
    assert recovered == 1
    assert stored_task.execution_status == "失败"
    assert stored_task.last_error == task_scheduler_module.ZOMBIE_TASK_ERROR


def _create_task(app_client: TestClient) -> int:
    client_id = _unwrap_success(
        app_client.post(
            "/api/clients/create",
            json={
                "name": "调度项目",
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
                "name": "调度提示词",
                "remark": "调度测试用提示词",
                "text": "请返回识别结果。",
                "format": 0,
            },
        ).json()
    )["id"]
    return _unwrap_success(
        app_client.post(
            "/api/tasks/create",
            json={
                "name": "调度任务",
                "client_id": client_id,
                "config_id": config_id,
                "interval_hours": 1,
                "execution_mode": "auto",
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
                },
            },
        ).json()
    )["id"]


def _unwrap_success(response_json: dict[str, Any]) -> Any:
    assert response_json["code"] == 0
    assert response_json["message"] == "success"
    return response_json["data"]


def _import_task_model():
    from aiSelfTest.models.task import Task

    return Task


def _import_task_scheduler_module():
    from aiSelfTest.services import task_scheduler

    return task_scheduler
