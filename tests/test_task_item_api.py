"""TaskItem 与动作层契约测试。"""

from __future__ import annotations

import json
import inspect
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from fastapi.params import Query
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
        "file_id": 101,
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
        source_id=9001,
        name="白鹭",
        score=0.91,
        det_name="鸟",
        det_score=0.81,
        track_ids="1001",
        sp_amount=1,
        llm_name="白鹭",
        llm_det_name="鸟",
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
        file_id=201,
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
        file_id=202,
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


def test_task_item_list_route_uses_annotated_query_metadata(app_client: TestClient) -> None:
    """任务项列表查询参数不应把 FastAPI Query 对象作为函数默认值。"""

    from aiSelfTest.api.task import list_task_items_route

    signature = inspect.signature(list_task_items_route)
    hints = get_type_hints(list_task_items_route, include_extras=True)
    query_param_names = ("task_id", "media_type", "status", "confirm_state", "page", "page_size")

    assert signature.parameters["task_id"].default is inspect.Signature.empty
    for name in query_param_names:
        parameter = signature.parameters[name]
        assert not isinstance(parameter.default, Query)

        hint = hints[name]
        assert get_origin(hint) is Annotated
        assert isinstance(get_args(hint)[1], Query)


def test_task_item_list_rejects_invalid_query_params(app_client: TestClient) -> None:
    """任务项列表接口应继续保留查询参数边界校验。"""

    invalid_requests = (
        {"task_id": 0},
        {"task_id": 1, "page": 0},
        {"task_id": 1, "page_size": 201},
    )

    for params in invalid_requests:
        response = app_client.get("/api/task-items/list", params=params)

        assert response.status_code == 400
        assert response.json()["code"] == 1001


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
    assert data["review_rows"][0]["source_id"] == 9001
    assert data["review_rows"][0]["det_name"] == "鸟"
    assert data["review_rows"][0]["det_score"] == 0.81
    assert data["review_rows"][0]["llm_det_name"] == "鸟"
    assert data["review_rows"][0]["status"] == "修改"
    assert data["review_rows"][0]["track_ids"] == "1001"


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
        file_id=203,
        file_fid="fid-image-1",
        file_bmp=1,
        result_file_data="",
    )
    _, task_item_data_model = import_task_item_models()
    default_data.source_id = 9000
    default_data.det_name = "鸟"
    default_data.det_score = 0.8
    default_data.llm_det_name = "鸟"
    default_data.status = "默认"
    default_data.minx = 1
    default_data.miny = 2
    default_data.maxx = 30
    default_data.maxy = 40
    db_session.add(default_data)

    review_rows = [
        task_item_data_model(
            task_item_id=task_item.id,
            source_id=9002,
            name="苍鹭",
            score=0.88,
            det_name="鸟",
            det_score=0.78,
            track_ids="1002",
            sp_amount=1,
            minx=10,
            miny=20,
            maxx=110,
            maxy=120,
            llm_name="夜鹭",
            llm_det_name="鸟",
            status="修改",
        ),
        task_item_data_model(
            task_item_id=task_item.id,
            name="",
            score=0,
            det_name="",
            det_score=0,
            track_ids="",
            sp_amount=1,
            minx=50,
            miny=60,
            maxx=90,
            maxy=100,
            llm_name="人",
            llm_det_name="人",
            status="新增",
        ),
        task_item_data_model(
            task_item_id=task_item.id,
            source_id=9003,
            name="车",
            score=0.77,
            det_name="车",
            det_score=0.73,
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
    assert rows_by_status["默认"]["source_id"] == 9000
    assert rows_by_status["默认"]["det_name"] == "鸟"
    assert rows_by_status["默认"]["det_score"] == 0.8
    assert rows_by_status["默认"]["llm_det_name"] == "鸟"
    assert data["media"]["result_file_url"] is None


def test_video_task_item_detail_returns_videojson_url_without_parsing(
    app_client: TestClient,
    db_session: Session,
) -> None:
    """视频详情只暴露 videojson 静态 URL 与 track_ids，不解析 videojson 内容。"""

    from aiSelfTest.config import get_settings

    _, _, task_id = _create_base_entities(app_client)
    task_item, task_item_data = _seed_task_item(db_session, task_id)
    item_dir = get_settings().data_dir / "task_files" / "video-overlay-task"
    item_dir.mkdir(parents=True, exist_ok=True)
    video_path = item_dir / "video-1.mp4"
    videojson_path = item_dir / "video-1.videojson"
    video_path.write_bytes(b"fake video")
    videojson_path.write_text(
        '[{"not": "a valid two dimensional videojson but should still be served"}]',
        encoding="utf-8",
    )
    task_item.file_path = str(video_path)
    db_session.add(task_item)
    db_session.commit()

    response = app_client.get(f"/api/task-items/detail/{task_item.id}")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["media"]["url"] == "/api/task-files/video-overlay-task/video-1.mp4"
    assert data["media"]["result_file_url"] == "/api/task-files/video-overlay-task/video-1.videojson"
    assert data["review_rows"][0]["task_item_data_id"] == task_item_data.id
    assert data["review_rows"][0]["track_ids"] == "1001"

    static_response = app_client.get(data["media"]["result_file_url"])
    assert static_response.status_code == 200
    assert "valid two dimensional" in static_response.text


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
    confirm_item, confirm_data = _seed_task_item(db_session, task_id, file_id=301)
    reject_item, reject_data = _seed_task_item(db_session, task_id, file_id=302)
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
    first, _ = _seed_task_item(db_session, task_id, file_id=401, file_fid="fid-first")
    second, second_data = _seed_task_item(db_session, task_id, file_id=402, file_fid="fid-second")

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


def test_task_item_submit_actions_are_not_registered(
    app_client: TestClient,
) -> None:
    """旧单个提交和旧批量提交接口应删除。"""

    single_response = app_client.post(
        "/api/task-items/action-submit",
        json={"task_item_id": 1},
    )
    batch_response = app_client.post(
        "/api/task-items/action-submit-task",
        json={"task_id": 1},
    )

    assert single_response.status_code == 404
    assert batch_response.status_code == 404


def test_task_item_submit_payload_uses_final_record_data_without_deleted_rows() -> None:
    """远端提交应提交最终 recordData，并仅为上游原始行附带明细 id。"""

    from aiSelfTest.models.task import TaskItemData
    from aiSelfTest.services.task_submission import AiPollingPayloadBuilder

    task_item_model, task_item_data_model = import_task_item_models()
    task_item = task_item_model(
        task_id=1,
        name="payload.mp4",
        device_name="device-1",
        file_num="file-001",
        file_extension="mp4",
        file_url="https://example.com/video.mp4",
        file_id=701,
        file_fid="fid-payload",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=2,
        result_file_data="",
        id_type=0,
        status=TaskItemStatus.CONFIRMED.value,
    )
    default_row = TaskItemData(
        task_item_id=1,
        source_id=7101,
        name="白鹭",
        score=0.91,
        det_name="鸟",
        det_score=0.71,
        track_ids="1001",
        sp_amount=1,
        minx=1,
        miny=2,
        maxx=10,
        maxy=12,
        llm_det_name="兽",
        status=TaskItemDataStatus.DEFAULT.value,
    )
    update_row = task_item_data_model(
        task_item_id=1,
        source_id=7102,
        name="苍鹭",
        score=0.8,
        det_name="鸟",
        det_score=0.72,
        track_ids="track-2",
        sp_amount=1,
        minx=20,
        miny=30,
        maxx=40,
        maxy=50,
        llm_name="夜鹭",
        llm_det_name="鸟",
        status=TaskItemDataStatus.UPDATE.value,
    )
    add_row = task_item_data_model(
        task_item_id=1,
        name="",
        score=0,
        det_name="",
        det_score=0,
        track_ids="",
        sp_amount=1,
        minx=60,
        miny=70,
        maxx=80,
        maxy=90,
        llm_name="人",
        llm_det_name="人",
        status=TaskItemDataStatus.ADD.value,
    )
    delete_row = task_item_data_model(
        task_item_id=1,
        source_id=7103,
        name="车",
        score=0.7,
        det_name="车",
        det_score=0.7,
        track_ids="track-3",
        sp_amount=1,
        llm_name=None,
        status=TaskItemDataStatus.DELETE.value,
    )

    payload = AiPollingPayloadBuilder().build_payload(
        task_item,
        [default_row, update_row, add_row, delete_row],
        datetime(2026, 4, 30, 9, 10, 11),
    )

    assert payload["id"] == 701
    assert payload["recordData"] == [
        {
            "id": 7101,
            "name": "白鹭",
            "score": 0.91,
            "detName": "鸟",
            "detScore": 0.71,
            "trackIds": "1001",
            "spAmount": 1,
            "minx": 1,
            "miny": 2,
            "maxx": 10,
            "maxy": 12,
        },
        {
            "id": 7102,
            "name": "夜鹭",
            "score": 0.8,
            "detName": "鸟",
            "detScore": 0.72,
            "trackIds": "track-2",
            "spAmount": 1,
            "minx": 20,
            "miny": 30,
            "maxx": 40,
            "maxy": 50,
        },
        {
            "name": "人",
            "score": 0,
            "detName": "人",
            "detScore": 0,
            "trackIds": "",
            "spAmount": 1,
            "minx": 60,
            "miny": 70,
            "maxx": 80,
            "maxy": 90,
        },
    ]


def test_training_artifacts_use_configured_hierarchical_directory(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """提交训练文件应按日期、模块、租户和设备分层保存。"""

    from aiSelfTest.config import get_settings
    from aiSelfTest.models.client import Client
    from aiSelfTest.models.task import Task
    from aiSelfTest.services.task_submission import TaskSubmissionService

    _, _, task_id = _create_base_entities(app_client)
    task = db_session.get(Task, task_id)
    assert task is not None
    task.filters_json = json.dumps({"module": "camera"}, ensure_ascii=False)
    client = db_session.get(Client, task.client_id)
    assert client is not None
    client.tenant_name = "测试租户"
    db_session.add(task)
    db_session.add(client)

    source_dir = get_settings().data_dir / "source-media"
    source_dir.mkdir(parents=True, exist_ok=True)
    media_path = source_dir / "image-1.jpg"
    media_path.write_bytes(b"fake image")

    task_item, row = _seed_task_item(
        db_session,
        task_id,
        name="image-1.jpg",
        device_name="设备A",
        file_extension="jpg",
        file_url="https://example.com/image.jpg",
        file_id=901,
        file_fid="fid-image-training",
        file_bmp=1,
        result_file_data="",
        file_path=media_path.as_posix(),
        confirm_state=TaskItemConfirmState.CONFIRMED.value,
        status=TaskItemStatus.CONFIRMED.value,
    )
    row.status = TaskItemDataStatus.DEFAULT.value
    row.minx = 1
    row.miny = 2
    row.maxx = 30
    row.maxy = 40
    db_session.add(row)
    db_session.commit()
    _install_submit_success_mock(monkeypatch)

    result = TaskSubmissionService(db_session).submit_task_item_outputs(
        task_item,
        now=datetime(2026, 4, 30, 9, 10, 11),
    )

    target_dir = (
        get_settings().training_save_dir
        / "20260430_AI自检_红外相机_保存"
        / "测试租户"
        / "设备A"
    )
    copied_media_path = target_dir / "image-1.jpg"
    datajson_path = target_dir / "image-1.datajson"
    assert copied_media_path.read_bytes() == b"fake image"
    assert Path(result.annotation_path) == datajson_path
    assert json.loads(datajson_path.read_text(encoding="utf-8")) == [
        {
            "score": 0.91,
            "detScore": 0.81,
            "miny": 2,
            "trackIds": "1001",
            "minx": 1,
            "maxy": 40,
            "maxx": 30,
            "name": "白鹭",
            "type": 0,
            "detName": "鸟",
        }
    ]


def test_video_training_artifacts_copy_videojson_when_present(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """视频训练保存应复制同目录 videojson，并按媒体主干命名。"""

    from aiSelfTest.config import get_settings
    from aiSelfTest.models.client import Client
    from aiSelfTest.models.task import Task
    from aiSelfTest.services.task_submission import TaskSubmissionService

    _, _, task_id = _create_base_entities(app_client)
    task = db_session.get(Task, task_id)
    assert task is not None
    task.filters_json = json.dumps({"module": "video"}, ensure_ascii=False)
    client = db_session.get(Client, task.client_id)
    assert client is not None
    client.tenant_name = "视频租户"
    db_session.add(task)
    db_session.add(client)

    source_dir = get_settings().data_dir / "source-video"
    source_dir.mkdir(parents=True, exist_ok=True)
    media_path = source_dir / "video-1.mp4"
    media_path.write_bytes(b"fake video")
    (source_dir / "upstream-result.videojson").write_text("[[]]", encoding="utf-8")

    task_item, _ = _seed_task_item(
        db_session,
        task_id,
        device_name="视频设备",
        file_path=media_path.as_posix(),
        confirm_state=TaskItemConfirmState.CONFIRMED.value,
        status=TaskItemStatus.CONFIRMED.value,
    )
    db_session.commit()
    _install_submit_success_mock(monkeypatch)

    TaskSubmissionService(db_session).submit_task_item_outputs(
        task_item,
        now=datetime(2026, 4, 30, 9, 10, 11),
    )

    target_dir = (
        get_settings().training_save_dir
        / "20260430_AI自检_视频_保存"
        / "视频租户"
        / "视频设备"
    )
    assert (target_dir / "video-1.mp4").read_bytes() == b"fake video"
    assert (target_dir / "video-1.videojson").read_text(encoding="utf-8") == "[[]]"
    assert (target_dir / "video-1.datajson").is_file()


def test_video_training_artifacts_missing_videojson_does_not_fail(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """视频源目录没有 videojson 时，训练保存仍应成功。"""

    from aiSelfTest.config import get_settings
    from aiSelfTest.models.client import Client
    from aiSelfTest.models.task import Task
    from aiSelfTest.services.task_submission import TaskSubmissionService

    _, _, task_id = _create_base_entities(app_client)
    task = db_session.get(Task, task_id)
    assert task is not None
    client = db_session.get(Client, task.client_id)
    assert client is not None
    client.tenant_name = "缺失租户"
    db_session.add(client)

    source_dir = get_settings().data_dir / "source-video-missing-result"
    source_dir.mkdir(parents=True, exist_ok=True)
    media_path = source_dir / "video-missing.mp4"
    media_path.write_bytes(b"fake video")

    task_item, _ = _seed_task_item(
        db_session,
        task_id,
        name="video-missing.mp4",
        device_name="缺失设备",
        file_id=902,
        file_fid="fid-video-missing",
        file_path=media_path.as_posix(),
        confirm_state=TaskItemConfirmState.CONFIRMED.value,
        status=TaskItemStatus.CONFIRMED.value,
    )
    db_session.commit()
    _install_submit_success_mock(monkeypatch)

    result = TaskSubmissionService(db_session).submit_task_item_outputs(
        task_item,
        now=datetime(2026, 4, 30, 9, 10, 11),
    )

    target_dir = (
        get_settings().training_save_dir
        / "20260430_AI自检_红外相机_保存"
        / "缺失租户"
        / "缺失设备"
    )
    assert Path(result.annotation_path) == target_dir / "video-missing.datajson"
    assert (target_dir / "video-missing.mp4").is_file()
    assert not (target_dir / "video-missing.videojson").exists()


def test_task_submit_route_enqueues_submission(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """任务级提交接口只入队并返回提交保存记录。"""

    _, _, task_id = _create_base_entities(app_client)
    _seed_task_item(
        db_session,
        task_id,
        confirm_state=TaskItemConfirmState.CONFIRMED.value,
        status=TaskItemStatus.CONFIRMED.value,
    )
    enqueued: list[tuple[int, str]] = []

    from aiSelfTest.services.task_submission_job import TaskSubmissionJobService

    monkeypatch.setattr(
        TaskSubmissionJobService,
        "_enqueue_submission",
        staticmethod(lambda submission_id, celery_task_id: enqueued.append((submission_id, celery_task_id))),
    )

    response = app_client.post(f"/api/tasks/action-submit/{task_id}")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["task_id"] == task_id
    assert data["status"] == "queued"
    assert data["total_count"] == 1
    assert enqueued == [(data["submission_id"], f"task-submission-{data['submission_id']}")]

    detail_response = app_client.get(f"/api/tasks/submission-detail/{data['submission_id']}")
    current_response = app_client.get(f"/api/tasks/submission-current/{task_id}")
    assert _unwrap_success(detail_response.json())["submission_id"] == data["submission_id"]
    assert _unwrap_success(current_response.json())["submission_id"] == data["submission_id"]


def test_task_submit_route_rejects_duplicate_running_submission(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    enqueued: list[tuple[int, str]] = []

    from aiSelfTest.services.task_submission_job import TaskSubmissionJobService

    monkeypatch.setattr(
        TaskSubmissionJobService,
        "_enqueue_submission",
        staticmethod(lambda submission_id, celery_task_id: enqueued.append((submission_id, celery_task_id))),
    )

    first_response = app_client.post(f"/api/tasks/action-submit/{task_id}")
    second_response = app_client.post(f"/api/tasks/action-submit/{task_id}")

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json()["code"] == 3002
    assert second_response.json()["data"]["submission_id"] == _unwrap_success(first_response.json())["submission_id"]
    assert len(enqueued) == 1


def test_task_item_submit_unconfirmed_item_is_not_registered(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item, _ = _seed_task_item(db_session, task_id, confirm_state=TaskItemConfirmState.PENDING.value)

    response = app_client.post("/api/task-items/action-submit", json={"task_item_id": task_item.id})

    assert response.status_code == 404
    db_session.refresh(task_item)
    assert task_item.remote_state == TaskItemRemoteState.PENDING.value


def test_task_item_submit_skipped_item_is_not_registered(
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

    assert response.status_code == 404
    db_session.refresh(task_item)
    assert task_item.remote_state == TaskItemRemoteState.PENDING.value


def test_task_finish_state_refreshes_after_submission_worker(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_model, task_item_model = import_task_and_item_models()
    from aiSelfTest.config import get_settings

    source_dir = get_settings().data_dir / "finish-submit-source"
    source_dir.mkdir(parents=True, exist_ok=True)
    media_path = source_dir / "finish.mp4"
    media_path.write_bytes(b"fake finish video")
    first, _ = _seed_task_item(
        db_session,
        task_id,
        file_id=601,
        file_fid="fid-submit",
        file_path=media_path.as_posix(),
        confirm_state=TaskItemConfirmState.CONFIRMED.value,
        status="已确认",
    )
    second, _ = _seed_task_item(
        db_session,
        task_id,
        file_id=602,
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
    _install_submit_success_mock(monkeypatch)

    skip_response = app_client.post(
        "/api/task-items/action-reject",
        json={"task_item_id": second.id, "reason": "无需提交"},
    )
    from aiSelfTest.services.task_submission_job import TaskSubmissionJobService

    monkeypatch.setattr(TaskSubmissionJobService, "_enqueue_submission", staticmethod(lambda *_args: None))
    TaskSubmissionJobService(db_session).submit(first.task_id)
    submission_model = _import_task_submission_model()
    submission = db_session.exec(select(submission_model).where(submission_model.task_id == task_id)).one()
    TaskSubmissionJobService(db_session).execute(submission.id)

    assert skip_response.status_code == 200
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


def _import_task_submission_model():
    from aiSelfTest.models.task import TaskSubmission

    return TaskSubmission


def _install_submit_success_mock(monkeypatch, response_json: Any = True) -> list[dict[str, Any]]:
    """安装远端提交桩，记录提交 payload。"""

    from aiSelfTest.services import task_submission

    submitted_payloads: list[dict[str, Any]] = []

    class FakeClientApi:
        def __init__(self, session: Session, client_id: int) -> None:
            self.session = session
            self.client_id = client_id

        def update_ai_polling_result(self, payload: dict[str, Any]) -> Any:
            submitted_payloads.append(payload)
            return SimpleNamespace(status_code=200, text=str(response_json), json=lambda: response_json)

    monkeypatch.setattr(task_submission, "ClientApi", FakeClientApi)
    return submitted_payloads


def _training_datajson_path(task_item: Any) -> Path:
    from aiSelfTest.config import get_settings

    media_stem = Path(task_item.file_path or task_item.name).stem
    matches = list(get_settings().training_save_dir.rglob(f"{media_stem}.datajson"))
    assert matches
    return matches[0]
