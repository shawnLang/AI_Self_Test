"""TaskItem 与动作层契约测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from aiSelfTest.models.task import (
    TaskItemConfirmState,
    TaskItemDataStatus,
    TaskItemLlmState,
    TaskItemRemoteState,
    TaskItemStatus,
    TaskItemTrainState,
)


def _unwrap_success(response_json: dict[str, Any]) -> Any:
    assert response_json["code"] == 0
    assert response_json["message"] == "success"
    return response_json["data"]


def _create_client_payload() -> dict[str, Any]:
    return {
        "name": "任务项目",
        "apiUrl": "https://example.com",
        "account": "task-admin",
        "password": "secret-123",
        "status": "启用",
    }


def _create_config_payload() -> dict[str, Any]:
    return {
        "name": "任务提示词",
        "remark": "任务测试用提示词",
        "text": "请返回识别结果。",
        "format": 0,
    }


def _create_task_payload(client_id: int, config_id: int) -> dict[str, Any]:
    return {
        "name": "任务工作区-001",
        "client_id": client_id,
        "config_id": config_id,
        "interval_hours": 1,
        "execution_mode": "manual",
        "auto_execute": False,
        "filters": {
            "classify_list": [1, 2],
            "keyword": "",
            "sp_name": "",
            "start_at": "2026-04-20",
            "end_at": "2026-04-25",
            "media_types": ["image", "video"],
            "upload_types": [],
            "identify_source": [],
        },
    }


def _create_base_entities(app_client: TestClient) -> tuple[int, int, int]:
    client_response = app_client.post("/api/clients/create", json=_create_client_payload())
    config_response = app_client.post("/api/configs/create", json=_create_config_payload())

    client_id = _unwrap_success(client_response.json())["id"]
    config_id = _unwrap_success(config_response.json())["id"]

    task_response = app_client.post(
        "/api/tasks/create",
        json=_create_task_payload(client_id, config_id),
    )
    task_id = _unwrap_success(task_response.json())["id"]
    return client_id, config_id, task_id


def _seed_task_item(
    db_session: Session,
    task_id: int,
    **overrides: Any,
) -> tuple[Any, Any]:
    task_item_model, task_item_data_model = import_task_item_models()

    task_item_payload = {
        "task_id": task_id,
        "name": "video-1.mp4",
        "device_name": "device-1",
        "file_num": "file-001",
        "file_extension": "mp4",
        "file_url": "https://example.com/video.mp4",
        "file_id": "file-001",
        "file_fid": "fid-001",
        "sp_name_list": "白鹭",
        "classify": 1,
        "file_bmp": 2,
        "result_file_data": "https://example.com/result.json",
        "id_type": 0,
        "status": "待复核",
        "down_state": True,
        "llm_state": TaskItemLlmState.SUCCESS.value,
        "confirm_state": TaskItemConfirmState.PENDING.value,
        "remote_state": TaskItemRemoteState.PENDING.value,
    }
    task_item_payload.update(overrides)
    task_item = task_item_model(**task_item_payload)
    db_session.add(task_item)
    db_session.commit()
    db_session.refresh(task_item)

    task_item_data = task_item_data_model(
        task_item_id=task_item.id,
        name="白鹭",
        score=0.91,
        track_ids="1001",
        sp_amount=1,
        llm_name="白鹭",
        status="修改",
    )
    db_session.add(task_item_data)
    db_session.commit()
    db_session.refresh(task_item_data)
    return task_item, task_item_data


def test_task_item_list_returns_items_for_task(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item, _ = _seed_task_item(db_session, task_id)

    response = app_client.get(f"/api/task-items/list?task_id={task_id}")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["total"] == 1
    assert data["items"][0]["id"] == task_item.id
    assert data["items"][0]["media_type"] == "video"


def test_task_item_list_filters_by_media_status_and_confirm_state(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    _seed_task_item(
        db_session,
        task_id,
        name="image-confirmed.jpg",
        file_extension="jpg",
        file_url="https://example.com/image.jpg",
        file_id="file-image-confirmed",
        file_fid="fid-image-confirmed",
        file_bmp=1,
        result_file_data="",
        status="待复核",
        confirm_state=TaskItemConfirmState.CONFIRMED.value,
    )
    _seed_task_item(
        db_session,
        task_id,
        name="video-pending.mp4",
        file_id="file-video-pending",
        file_fid="fid-video-pending",
        status="待复核",
        confirm_state=TaskItemConfirmState.PENDING.value,
    )

    response = app_client.get(
        "/api/task-items/list",
        params={
            "task_id": task_id,
            "media_type": "image",
            "status": "待复核",
            "confirm_state": TaskItemConfirmState.CONFIRMED.value,
        },
    )

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["total"] == 1
    assert data["items"][0]["name"] == "image-confirmed.jpg"
    assert data["items"][0]["media_type"] == "image"


def test_task_item_detail_returns_review_rows(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item, task_item_data = _seed_task_item(db_session, task_id)

    response = app_client.get(f"/api/task-items/detail/{task_item.id}")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["id"] == task_item.id
    assert data["review_rows"][0]["task_item_data_id"] == task_item_data.id
    assert data["review_rows"][0]["status"] == "修改"


def test_task_item_detail_returns_bbox_and_status_based_review_summary(
    app_client: TestClient,
    db_session: Session,
) -> None:
    """复核详情应按 TaskItemDataStatus 返回绘框数据和统计摘要。"""

    _, _, task_id = _create_base_entities(app_client)
    task_item, default_data = _seed_task_item(
        db_session,
        task_id,
        name="image-1.jpg",
        file_extension="jpg",
        file_url="https://example.com/image.jpg",
        file_id="file-image-1",
        file_fid="fid-image-1",
        file_bmp=1,
        result_file_data="",
    )
    _, task_item_data_model = import_task_item_models()
    default_data.status = "默认"
    default_data.minx = 1
    default_data.miny = 2
    default_data.maxx = 30
    default_data.maxy = 40
    db_session.add(default_data)

    review_rows = [
        task_item_data_model(
            task_item_id=task_item.id,
            name="苍鹭",
            score=0.88,
            track_ids="1002",
            sp_amount=1,
            minx=10,
            miny=20,
            maxx=110,
            maxy=120,
            llm_name="夜鹭",
            status="修改",
        ),
        task_item_data_model(
            task_item_id=task_item.id,
            name="",
            score=0,
            track_ids="",
            sp_amount=1,
            minx=50,
            miny=60,
            maxx=90,
            maxy=100,
            llm_name="人",
            status="新增",
        ),
        task_item_data_model(
            task_item_id=task_item.id,
            name="车",
            score=0.77,
            track_ids="1003",
            sp_amount=1,
            minx=130,
            miny=140,
            maxx=170,
            maxy=180,
            llm_name=None,
            status="删除",
        ),
    ]
    for row in review_rows:
        db_session.add(row)
    db_session.commit()

    response = app_client.get(f"/api/task-items/detail/{task_item.id}")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["review_summary"] == {
        "submit_count": 3,
        "exclude_count": 1,
        "submit_empty": False,
    }
    rows_by_status = {row["status"]: row for row in data["review_rows"]}
    assert rows_by_status["新增"]["bbox"] == {
        "minx": 50.0,
        "miny": 60.0,
        "maxx": 90.0,
        "maxy": 100.0,
    }
    assert rows_by_status["新增"]["source_size"] is not None
    assert rows_by_status["默认"]["bbox"] == {
        "minx": 1.0,
        "miny": 2.0,
        "maxx": 30.0,
        "maxy": 40.0,
    }


def test_task_item_confirm_action_updates_confirm_state(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item, _ = _seed_task_item(db_session, task_id)
    task_item_model, _ = import_task_item_models()

    response = app_client.post("/api/task-items/action-confirm", json={"task_item_id": task_item.id})

    assert response.status_code == 200
    db_session.refresh(task_item)
    stored = db_session.exec(select(task_item_model).where(task_item_model.id == task_item.id)).one()
    assert stored.confirm_state == TaskItemConfirmState.CONFIRMED.value
    assert stored.remote_state == TaskItemRemoteState.PENDING.value
    assert stored.status == "已确认"


def test_task_item_reject_action_marks_item_skipped_without_deleting_source(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item, _ = _seed_task_item(db_session, task_id)
    task_item_model, _ = import_task_item_models()

    response = app_client.post(
        "/api/task-items/action-reject",
        json={"task_item_id": task_item.id, "reason": "manual_review_required"},
    )

    assert response.status_code == 200
    db_session.expire_all()
    stored = db_session.exec(select(task_item_model).where(task_item_model.id == task_item.id)).one_or_none()
    assert stored is not None
    assert stored.confirm_state == TaskItemConfirmState.SKIPPED.value
    assert stored.status == "已跳过"
    assert stored.remote_state == TaskItemRemoteState.PENDING.value


def test_task_item_confirm_and_reject_actions_block_matched_items(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    confirm_item, confirm_data = _seed_task_item(db_session, task_id, file_id="file-confirm")
    reject_item, reject_data = _seed_task_item(db_session, task_id, file_id="file-reject")
    confirm_data.status = TaskItemDataStatus.DEFAULT.value
    reject_data.status = TaskItemDataStatus.DEFAULT.value
    db_session.add(confirm_data)
    db_session.add(reject_data)
    db_session.commit()

    confirm_response = app_client.post(
        "/api/task-items/action-confirm",
        json={"task_item_id": confirm_item.id},
    )
    reject_response = app_client.post(
        "/api/task-items/action-reject",
        json={"task_item_id": reject_item.id, "reason": "manual_skip"},
    )

    assert confirm_response.status_code == 400
    assert confirm_response.json()["code"] == 1001
    assert reject_response.status_code == 400
    assert reject_response.json()["code"] == 1001
    db_session.refresh(confirm_item)
    db_session.refresh(reject_item)
    assert confirm_item.confirm_state == TaskItemConfirmState.PENDING.value
    assert reject_item.confirm_state == TaskItemConfirmState.PENDING.value


def test_task_item_update_row_action_updates_status_and_llm_name(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item, task_item_data = _seed_task_item(db_session, task_id)
    task_item_model, task_item_data_model = import_task_item_models()

    response = app_client.post(
        "/api/task-items/action-update-row",
        json={
            "task_item_id": task_item.id,
            "task_item_data_id": task_item_data.id,
            "status": TaskItemDataStatus.DEFAULT.value,
            "llm_name": "白鹭",
        },
    )

    assert response.status_code == 200
    db_session.expire_all()
    stored_item = db_session.exec(select(task_item_model).where(task_item_model.id == task_item.id)).one()
    stored_row = db_session.exec(
        select(task_item_data_model).where(task_item_data_model.id == task_item_data.id)
    ).one()
    assert stored_row.name == "白鹭"
    assert stored_row.llm_name == "白鹭"
    assert stored_row.status == TaskItemDataStatus.DEFAULT.value
    assert stored_item.status == TaskItemStatus.SKIPPED.value
    assert stored_item.confirm_state == TaskItemConfirmState.SKIPPED.value


def test_task_item_update_row_rejects_row_from_other_task_item(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    first, _ = _seed_task_item(db_session, task_id, file_id="file-first", file_fid="fid-first")
    second, second_data = _seed_task_item(db_session, task_id, file_id="file-second", file_fid="fid-second")

    response = app_client.post(
        "/api/task-items/action-update-row",
        json={
            "task_item_id": first.id,
            "task_item_data_id": second_data.id,
            "status": TaskItemDataStatus.UPDATE.value,
            "llm_name": "夜鹭",
        },
    )

    assert response.status_code == 404
    db_session.refresh(second_data)
    db_session.refresh(second)
    assert second_data.llm_name == "白鹭"
    assert second_data.status == "修改"
    assert second.status == "待复核"


def test_task_item_update_row_blocks_finished_item(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item, task_item_data = _seed_task_item(
        db_session,
        task_id,
        status=TaskItemStatus.FINISHED.value,
        confirm_state=TaskItemConfirmState.CONFIRMED.value,
        remote_state=TaskItemRemoteState.SUCCESS.value,
    )

    response = app_client.post(
        "/api/task-items/action-update-row",
        json={
            "task_item_id": task_item.id,
            "task_item_data_id": task_item_data.id,
            "status": TaskItemDataStatus.DEFAULT.value,
            "llm_name": "白鹭",
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == 1001


def test_task_item_delete_action_is_not_registered(app_client: TestClient) -> None:
    response = app_client.post(
        "/api/task-items/action-delete",
        json={"task_item_id": 1, "task_item_data_ids": [1]},
    )

    assert response.status_code == 404


def test_task_item_submit_action_returns_success(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item, _ = _seed_task_item(
        db_session,
        task_id,
        confirm_state=TaskItemConfirmState.CONFIRMED.value,
        status="已确认",
    )
    task_item_model, _ = import_task_item_models()

    response = app_client.post("/api/task-items/action-submit", json={"task_item_id": task_item.id})

    assert response.status_code == 200
    assert response.json()["code"] == 0
    db_session.expire_all()
    stored = db_session.exec(select(task_item_model).where(task_item_model.id == task_item.id)).one()
    assert stored.remote_state == TaskItemRemoteState.SUCCESS.value
    assert stored.train_state == TaskItemTrainState.SAVED.value
    assert stored.status == "已完成"
    assert _training_annotation_path(task_id, task_item.id).exists()


def test_task_item_submit_task_action_submits_all_confirmed_pending_items(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item_model, _ = import_task_item_models()
    pending_item, _ = _seed_task_item(
        db_session,
        task_id,
        file_id="file-pending-submit",
        file_fid="fid-pending-submit",
        confirm_state=TaskItemConfirmState.CONFIRMED.value,
        remote_state=TaskItemRemoteState.PENDING.value,
        status=TaskItemStatus.CONFIRMED.value,
    )
    retry_item, _ = _seed_task_item(
        db_session,
        task_id,
        file_id="file-retry-submit",
        file_fid="fid-retry-submit",
        confirm_state=TaskItemConfirmState.CONFIRMED.value,
        remote_state=TaskItemRemoteState.FAIL.value,
        status=TaskItemStatus.CONFIRMED.value,
    )
    skipped_item, _ = _seed_task_item(
        db_session,
        task_id,
        file_id="file-skipped",
        file_fid="fid-skipped",
        confirm_state=TaskItemConfirmState.SKIPPED.value,
        status=TaskItemStatus.SKIPPED.value,
    )
    pending_review_item, _ = _seed_task_item(
        db_session,
        task_id,
        file_id="file-pending-review",
        file_fid="fid-pending-review",
        confirm_state=TaskItemConfirmState.PENDING.value,
        status=TaskItemStatus.VERIFY_PENDING.value,
    )

    response = app_client.post("/api/task-items/action-submit-task", json={"task_id": task_id})

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["success_count"] == 2
    assert data["failure_count"] == 0
    assert {row["id"] for row in data["results"]} == {pending_item.id, retry_item.id}
    db_session.expire_all()
    rows = db_session.exec(select(task_item_model).where(task_item_model.task_id == task_id)).all()
    rows_by_id = {row.id: row for row in rows}
    assert rows_by_id[pending_item.id].status == TaskItemStatus.FINISHED.value
    assert rows_by_id[retry_item.id].remote_state == TaskItemRemoteState.SUCCESS.value
    assert rows_by_id[skipped_item.id].status == TaskItemStatus.SKIPPED.value
    assert rows_by_id[pending_review_item.id].status == TaskItemStatus.VERIFY_PENDING.value
    assert _training_annotation_path(task_id, pending_item.id).exists()
    assert _training_annotation_path(task_id, retry_item.id).exists()


def test_task_item_submit_unconfirmed_item_is_blocked(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item, _ = _seed_task_item(db_session, task_id, confirm_state=TaskItemConfirmState.PENDING.value)

    response = app_client.post("/api/task-items/action-submit", json={"task_item_id": task_item.id})

    assert response.status_code == 400
    assert response.json()["code"] == 1001
    db_session.refresh(task_item)
    assert task_item.remote_state == TaskItemRemoteState.PENDING.value


def test_task_item_submit_skipped_item_is_blocked(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item, _ = _seed_task_item(
        db_session,
        task_id,
        confirm_state=TaskItemConfirmState.SKIPPED.value,
        status=TaskItemStatus.SKIPPED.value,
    )

    response = app_client.post("/api/task-items/action-submit", json={"task_item_id": task_item.id})

    assert response.status_code == 400
    assert response.json()["code"] == 1001
    db_session.refresh(task_item)
    assert task_item.remote_state == TaskItemRemoteState.PENDING.value


def test_task_finishes_after_confirmed_submit_and_skipped_items(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_model, task_item_model = import_task_and_item_models()
    first, _ = _seed_task_item(
        db_session,
        task_id,
        file_id="file-submit",
        file_fid="fid-submit",
        confirm_state=TaskItemConfirmState.CONFIRMED.value,
        status="已确认",
    )
    second, _ = _seed_task_item(
        db_session,
        task_id,
        file_id="file-skip",
        file_fid="fid-skip",
        confirm_state=TaskItemConfirmState.PENDING.value,
        status="待复核",
    )
    task = db_session.get(task_model, task_id)
    task.execution_status = "核查"
    task.total_count = 2
    task.processed_count = 2
    db_session.add(task)
    db_session.commit()

    skip_response = app_client.post(
        "/api/task-items/action-reject",
        json={"task_item_id": second.id, "reason": "无需提交"},
    )
    submit_response = app_client.post("/api/task-items/action-submit", json={"task_item_id": first.id})

    assert skip_response.status_code == 200
    assert submit_response.status_code == 200
    db_session.expire_all()
    stored_task = db_session.get(task_model, task_id)
    stored_items = db_session.exec(select(task_item_model).where(task_item_model.task_id == task_id)).all()
    assert stored_task.execution_status == "结束"
    assert {item.status for item in stored_items} == {"已完成", "已跳过"}


def import_task_item_models():
    from aiSelfTest.models.task import TaskItem, TaskItemData

    return TaskItem, TaskItemData


def import_task_and_item_models():
    from aiSelfTest.models.task import Task, TaskItem

    return Task, TaskItem


def _training_annotation_path(task_id: int, task_item_id: int) -> Path:
    from aiSelfTest.config import get_settings

    return get_settings().data_dir / "training" / str(task_id) / str(task_item_id) / "annotation.json"
