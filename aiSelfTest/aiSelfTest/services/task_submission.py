"""TaskItem 提交与训练目录保存服务。"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aiSelfTest.config import get_settings
from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.client import Client
from aiSelfTest.models.task import (
    Task,
    TaskItem,
    TaskItemData,
    TaskItemDataStatus,
    TaskItemRemoteState,
    TaskItemStatus,
    TaskItemTrainState,
)
from aiSelfTest.services.client_auth import ClientApi
from loguru import logger
from sqlmodel import Session, select


MODULE_SAVE_NAME_MAP = {
    "camera": "红外相机",
    "video": "视频",
    "lure": "喂鸟器",
}
PATH_UNSAFE_CHARS = ('/', "\\", ":", "*", "?", '"', "<", ">", "|")


@dataclass(frozen=True)
class TaskSubmissionResult:
    """TaskItem 提交结果。"""

    remote_state: str
    train_state: str
    annotation_path: str


class AiPollingPayloadBuilder:
    """构造远端 AI 巡检结果提交载荷。"""

    def build_payload(
        self,
        task_item: TaskItem,
        data_rows: list[TaskItemData],
        submitted_at: datetime,
    ) -> dict[str, object]:
        """构造更新 AI 巡检结果接口载荷。"""

        if task_item.file_id is None:
            raise AppException(code=ErrorCode.PARAM_INVALID, message="任务项缺少上游 file_id", status_code=400)
        return {
            "id": task_item.file_id,
            "recordData": [
                row_payload
                for row in data_rows
                if (row_payload := self.build_record(row, submitted_at)) is not None
            ],
        }

    @staticmethod
    def build_record(row: TaskItemData, submitted_at: datetime) -> dict[str, object] | None:
        """构造单条最终识别结果记录，删除行不提交。"""

        if row.status == TaskItemDataStatus.DELETE.value:
            return None

        name = row.name if row.status == TaskItemDataStatus.DEFAULT.value else row.llm_name
        det_name = row.det_name if row.status == TaskItemDataStatus.DEFAULT.value else row.llm_det_name or row.det_name
        payload: dict[str, object] = {}
        if row.source_id is not None:
            payload["id"] = row.source_id
        payload.update({
            "name": name or "",
            "score": row.score,
            "detName": det_name or "",
            "detScore": row.det_score,
            "trackIds": row.track_ids,
            "spAmount": row.sp_amount,
            "minx": row.minx,
            "miny": row.miny,
            "maxx": row.maxx,
            "maxy": row.maxy,
        })
        return payload


class TrainingArtifactWriter:
    """保存训练目录中的媒体文件副本与标注 JSON。"""

    def save(
        self,
        session: Session,
        task_item: TaskItem,
        data_rows: list[TaskItemData],
        saved_at: datetime,
    ) -> Path:
        """保存训练目录中的媒体文件副本与标注 JSON。"""

        task = self._get_task_or_raise(session, task_item.task_id)
        client = self._get_client_or_raise(session, task.client_id)
        target_dir = self._build_target_dir(task, client, task_item, saved_at)
        target_dir.mkdir(parents=True, exist_ok=True)

        source_media_path = self._resolve_media_file(task_item.file_path)
        target_media_path = self._copy_media_file(source_media_path, target_dir)
        datajson_path = target_dir / self._build_sidecar_name(target_media_path, "datajson")
        self._write_datajson(datajson_path, data_rows)

        if task_item.file_bmp == 2:
            self._copy_videojson_if_exists(source_media_path, target_media_path, target_dir)

        return datajson_path

    @staticmethod
    def _get_task_or_raise(session: Session, task_id: int) -> Task:
        """查询训练保存所需任务信息。"""

        task = session.get(Task, task_id)
        if task is None:
            raise AppException(code=ErrorCode.NOT_FOUND, message="任务不存在", status_code=404)
        return task

    @staticmethod
    def _get_client_or_raise(session: Session, client_id: int) -> Client:
        """查询训练保存所需客户端信息。"""

        client = session.get(Client, client_id)
        if client is None:
            raise AppException(code=ErrorCode.NOT_FOUND, message="客户端不存在", status_code=404)
        return client

    def _build_target_dir(
        self,
        task: Task,
        client: Client,
        task_item: TaskItem,
        saved_at: datetime,
    ) -> Path:
        """按日期、模块、租户和设备生成训练保存目录。"""

        module_name = MODULE_SAVE_NAME_MAP.get(self._resolve_task_module(task), "红外相机")
        first_level = f"{saved_at:%Y%m%d}_AI自检_{module_name}_保存"
        tenant_name = self._sanitize_path_part(client.tenant_name, "未知租户")
        device_name = self._sanitize_path_part(task_item.device_name, "未知设备")
        return get_settings().training_save_dir / first_level / tenant_name / device_name

    @staticmethod
    def _resolve_task_module(task: Task) -> str:
        """从任务筛选条件中读取模块，缺省时按红外相机处理。"""

        if not task.filters_json:
            return "camera"
        try:
            payload = json.loads(task.filters_json)
        except json.JSONDecodeError:
            logger.warning("训练保存读取任务筛选条件失败 task_id={}", task.id)
            return "camera"
        if not isinstance(payload, dict):
            return "camera"
        module = str(payload.get("module") or "").strip()
        return module or "camera"

    @staticmethod
    def _sanitize_path_part(value: str | None, default: str) -> str:
        """清理目录名中的非法路径字符。"""

        text = str(value or "").strip() or default
        for char in PATH_UNSAFE_CHARS:
            text = text.replace(char, "_")
        return text or default

    @staticmethod
    def _resolve_media_file(source_path: str | None) -> Path:
        """校验媒体文件并返回源路径。"""

        if not source_path:
            raise AppException(code=ErrorCode.TASK_FAILED, message="训练保存缺少媒体文件路径", status_code=502)
        source = Path(source_path)
        if not source.exists() or not source.is_file():
            raise AppException(code=ErrorCode.TASK_FAILED, message=f"训练保存媒体文件不存在: {source}", status_code=502)
        return source

    @staticmethod
    def _copy_media_file(source: Path, target_dir: Path) -> Path:
        """复制媒体文件并返回目标媒体路径。"""

        target_path = target_dir / source.name
        shutil.copy2(source, target_path)
        return target_path

    @staticmethod
    def _build_sidecar_name(media_path: Path, extension: str) -> str:
        """按媒体主干生成伴随文件名，不保留原媒体后缀。"""

        return f"{media_path.stem}.{extension}"

    def _write_datajson(self, datajson_path: Path, data_rows: list[TaskItemData]) -> None:
        """写入 TaskItemData 训练明细。"""

        datajson_path.write_text(
            json.dumps(
                [self._build_datajson_row(row) for row in data_rows],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _copy_videojson_if_exists(self, source_media_path: Path, target_media_path: Path, target_dir: Path) -> None:
        """视频任务复制同目录 videojson，缺失时只记录警告。"""

        videojson_files = sorted(source_media_path.parent.glob("*.videojson"))
        if not videojson_files:
            logger.warning("训练保存未找到视频结果文件 media_path={}", source_media_path)
            return

        target_path = target_dir / self._build_sidecar_name(target_media_path, "videojson")
        shutil.copy2(videojson_files[0], target_path)

    @staticmethod
    def _build_datajson_row(row: TaskItemData) -> dict[str, object]:
        """构造训练 datajson 中的单条识别结果。"""

        return {
            "score": row.score,
            "detScore": row.det_score,
            "miny": row.miny,
            "trackIds": row.track_ids,
            "minx": row.minx,
            "maxy": row.maxy,
            "maxx": row.maxx,
            "name": row.name,
            "type": 0,
            "detName": row.det_name,
        }


class TaskSubmissionService:
    """编排 TaskItem 远端提交与训练目录保存。"""

    def __init__(
        self,
        session: Session,
        payload_builder: AiPollingPayloadBuilder | None = None,
        artifact_writer: TrainingArtifactWriter | None = None,
    ) -> None:
        """初始化提交服务依赖。"""

        self.session = session
        self.payload_builder = payload_builder or AiPollingPayloadBuilder()
        self.artifact_writer = artifact_writer or TrainingArtifactWriter()

    def submit_task_item_outputs(
        self,
        task_item: TaskItem,
        now: datetime | None = None,
    ) -> TaskSubmissionResult:
        """提交远端 AI 巡检结果，并保存训练目录标注文件。"""

        submitted_at = now or datetime.now()
        data_rows = self.session.exec(
            select(TaskItemData).where(TaskItemData.task_item_id == task_item.id)
        ).all()
        payload = self.payload_builder.build_payload(task_item, data_rows, submitted_at)

        try:
            response = ClientApi(self.session, self._task_item_client_id(task_item)).update_ai_polling_result(payload)
            self._ensure_remote_submit_success(response)
        except Exception as exc:
            self._mark_remote_failed(task_item, submitted_at, str(exc))
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message=f"远端提交失败: {exc}",
                status_code=502,
            ) from exc

        try:
            annotation_path = self.artifact_writer.save(self.session, task_item, data_rows, submitted_at)
            train_state = TaskItemTrainState.SAVED.value
        except Exception as exc:  # noqa: BLE001
            task_item.train_state = TaskItemTrainState.FAIL.value
            task_item.train_at = submitted_at
            task_item.updated_at = submitted_at
            self.session.add(task_item)
            self.session.commit()
            logger.exception("训练目录保存失败 task_item_id={}", task_item.id)
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message=f"训练目录保存失败: {exc}",
                status_code=502,
            ) from exc

        task_item.remote_state = TaskItemRemoteState.SUCCESS.value
        task_item.remote_error = None
        task_item.remote_at = submitted_at
        task_item.train_state = train_state
        task_item.train_at = submitted_at
        task_item.status = TaskItemStatus.FINISHED.value
        task_item.updated_at = submitted_at
        self.session.add(task_item)
        self.session.commit()
        self.session.refresh(task_item)
        logger.info(
            "任务项提交与训练保存完成 task_item_id={} annotation_path={}",
            task_item.id,
            annotation_path,
        )
        return TaskSubmissionResult(
            remote_state=task_item.remote_state or TaskItemRemoteState.SUCCESS.value,
            train_state=task_item.train_state or TaskItemTrainState.SAVED.value,
            annotation_path=annotation_path.as_posix(),
        )

    def _task_item_client_id(self, task_item: TaskItem) -> int:
        """返回 TaskItem 所属任务的客户端 ID。"""

        task = self.session.get(Task, task_item.task_id)
        if task is None:
            raise AppException(code=ErrorCode.NOT_FOUND, message="任务不存在", status_code=404)
        return task.client_id

    @staticmethod
    def _ensure_remote_submit_success(response: object) -> None:
        """校验上游提交响应。"""

        status_code = getattr(response, "status_code", None)
        if status_code != 200:
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message=f"远端提交接口失败 HTTP {status_code}: {getattr(response, 'text', '')}",
                status_code=502,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise AppException(code=ErrorCode.TASK_FAILED, message="远端提交接口返回非 JSON", status_code=502) from exc
        if payload is not True:
            raise AppException(code=ErrorCode.TASK_FAILED, message=f"远端提交接口返回失败: {payload}", status_code=502)

    def _mark_remote_failed(self, task_item: TaskItem, submitted_at: datetime, error: str) -> None:
        """记录远端提交失败状态。"""

        task_item.remote_state = TaskItemRemoteState.FAIL.value
        task_item.remote_error = error[:1000]
        task_item.remote_at = submitted_at
        task_item.status = TaskItemStatus.CONFIRMED.value
        task_item.updated_at = submitted_at
        self.session.add(task_item)
        self.session.commit()
