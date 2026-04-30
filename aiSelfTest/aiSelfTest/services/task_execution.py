"""Task 执行主干。

本模块提供媒体无关的 Task 执行主干：

1. 分页拉取上游文件记录并按 file_id 落库为 TaskItem。
2. 对新增 TaskItem 拉取详情 recordData 并落库为 TaskItemData。
3. 下载新增文件后，根据执行模式推进大模型识别、确认、提交与训练状态。
"""

from __future__ import annotations

import base64
import json
import mimetypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from loguru import logger
from requests.exceptions import RequestException
from sqlmodel import Session, select

from aiSelfTest.config import get_settings
from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.config import Config
from aiSelfTest.models.multimodal_model import MultimodalModel
from aiSelfTest.models.task import (
    Task,
    TaskExecutionMode,
    TaskExecutionStatus,
    TaskItem,
    TaskItemData,
    TaskItemDataStatus,
)
from aiSelfTest.schemas.multimodal_model import (
    MultimodalAttachmentPayload,
    MultimodalChatMessagePayload,
)
from aiSelfTest.schemas.task import TaskFiltersPayload
from aiSelfTest.services.client import get_client_or_raise
from aiSelfTest.services.client_auth import ClientApi, ClientUtils, UPSTREAM_FILE_DETAIL_PATH, UPSTREAM_FILE_PAGE_PATH
from aiSelfTest.services.multimodal_attachment import build_gateway_chat_payload
from aiSelfTest.services.multimodal_gateway import call_chat_endpoint, extract_chat_reply
from aiSelfTest.services.task_submission import submit_task_item_outputs
from aiSelfTest.services.utils import optional_float, format_dt, clip_end_at, parse_window_end, truncate

RUNNING_TASK_STATUSES = {
    TaskExecutionStatus.DOWN.value,
    TaskExecutionStatus.LLM.value,
    TaskExecutionStatus.VERIFY.value,
    TaskExecutionStatus.SUBMIT.value,
}

UPSTREAM_PAGE_SIZE = 100
MAX_UPSTREAM_PAGE_COUNT = 500
FILE_DOWNLOAD_PATH_PREFIX = "/weed/"
CLASSIFY_NAME_MAP = {
    1: "确种",
    2: "有效",
    3: "空拍",
    4: "处理中",
}
ID_TYPE_NAME_MAP = {
    0: "ai",
    1: "人工",
    3: "专家",
}


@dataclass(frozen=True)
class TaskExecutionWindow:
    """本次任务执行使用的时间窗口。"""

    start_at: str
    end_at: str
    should_fetch: bool = True


@dataclass(frozen=True)
class SourceTaskItemRecord:
    """上游文件记录的规范化形状。"""

    name: str
    file_fid: str
    file_url: str
    file_bmp: int
    file_id: str = ""
    device_name: str = ""
    file_num: str = ""
    file_extension: str = ""
    sp_name_list: str = ""
    classify: int = 1
    module: str = "camera"
    id_type: int = 0


@dataclass(frozen=True)
class SourceTaskItemDetail:
    """上游文件详情结果。"""

    result_file_data: str
    record_data: list[Mapping[str, Any]]


@dataclass(frozen=True)
class TaskExecutionResult:
    """任务执行结果摘要。"""

    task_id: int
    inserted_count: int
    skipped_count: int
    detail_row_count: int
    processed_count: int
    execution_status: str


@dataclass(frozen=True)
class TaskDownloadResult:
    """任务文件下载结果。"""

    file_path: str
    result_file_path: str | None = None


class TaskFileDownloader(Protocol):
    """任务文件下载协议。"""

    def download(
            self,
            session: Session,
            task: Task,
            task_item: TaskItem,
            source_record: SourceTaskItemRecord,
    ) -> TaskDownloadResult:
        """下载单个任务项需要的文件。"""


class TaskItemRecognizer(Protocol):
    """任务项大模型识别协议。"""

    def recognize(
            self,
            session: Session,
            task: Task,
            task_item: TaskItem,
            data_rows: Sequence[TaskItemData],
    ) -> Mapping[int, str]:
        """识别任务项并按 TaskItemData ID 返回名称。"""


class AuthenticatedTaskExecutionSource:
    """通过已配置客户端认证信息调用真实上游接口。"""

    @staticmethod
    def media_types_to_file_bmp(media_types: Sequence[str]) -> list[int]:
        """把前端媒体类型转换为上游 fileBmp 枚举。"""

        values: list[int] = []
        mapping = {"image": 1, "video": 2}
        for media_type in media_types:
            value = mapping.get(media_type)
            if value is not None and value not in values:
                values.append(value)
        return values

    @staticmethod
    def normalize_window_boundary(value: str, end_of_day: bool) -> str:
        """把日期或日期时间规整为上游需要的标准时间字符串。"""

        text = (value or "").strip()
        if not text:
            return ""
        if len(text) == 10:
            suffix = "23:59:59" if end_of_day else "00:00:00"
            return f"{text} {suffix}"

        normalized = text.replace("Z", "+00:00")
        try:
            return format_dt(datetime.fromisoformat(normalized))
        except ValueError:
            return text

    def build_upstream_page_payload(self, filters: TaskFiltersPayload, window: TaskExecutionWindow, current: int,
                                    size: int) -> dict[str, Any]:
        """把本地任务筛选条件转换为上游分页查询请求体。"""

        payload: dict[str, Any] = {
            "size": size,
            "current": current,
            "keyword": filters.keyword,
            "spName": filters.sp_name,
            "startTime": self.normalize_window_boundary(window.start_at, end_of_day=False),
            "endTime": self.normalize_window_boundary(window.end_at, end_of_day=True),
            "sortColumn": "fe.created_time",
            "sortOrder": "ASC",
        }
        if filters.classify_list:
            payload["classifyList"] = filters.classify_list
        if filters.media_types:
            payload["fileBmp"] = self.media_types_to_file_bmp(filters.media_types)
        if filters.upload_types:
            payload["uploadType"] = filters.upload_types
        if filters.identify_source:
            payload["idWayList"] = filters.identify_source
        if filters.module is not None:
            payload["module"] = filters.module
        else:
            payload["module"] = "camera"
        return payload

    @staticmethod
    def extract_response_payload(response: Any, path: str) -> Any:
        """校验上游响应状态并兼容提取业务数据。"""

        if response.status_code != 200:
            logger.warning(
                "客户端[{}]接口返回非成功状态: status={}, body={}",
                path,
                response.status_code,
                getattr(response, "text", ""),
            )
            raise AppException(code=ErrorCode.TASK_FAILED, message=f"客户端[{path}]接口请求失败", status_code=502)

        try:
            payload = response.json()
        except ValueError as exc:
            logger.warning("客户端[{}]接口返回非 JSON 数据: body={}", path, getattr(response, "text", ""))
            raise AppException(code=ErrorCode.TASK_FAILED, message=f"客户端[{path}]接口返回格式错误",
                               status_code=502) from exc

        if isinstance(payload, Mapping):
            response_code = payload.get("code")
            if response_code not in (None, 0, "0", 200, "200"):
                message = payload.get("message", "接口业务失败")
                logger.warning(f"客户端[{path}]接口返回业务错误: code={response_code}, message={message}")
                raise AppException(code=ErrorCode.TASK_FAILED, message=message, status_code=502)
            data = payload.get("data")
            if isinstance(data, (Mapping, list)):
                return data
        return payload

    def fetch_task_items(self, session: Session, task: Task, filters: TaskFiltersPayload,
                         window: TaskExecutionWindow) -> Sequence[Mapping[str, Any]]:
        """分页拉取符合任务筛选条件的真实上游文件。"""

        all_records: list[Mapping[str, Any]] = []
        current = 1
        client_api = ClientApi(session, task.client_id)
        auth_result = client_api.authenticate_client_model()
        headers = {"Authorization": auth_result.client.access_token}
        page_url = ClientUtils.build_url(auth_result.client.api_url, UPSTREAM_FILE_PAGE_PATH)
        timeout = get_settings().request_timeout_seconds

        for _ in range(MAX_UPSTREAM_PAGE_COUNT):
            payload = self.build_upstream_page_payload(filters, window, current=current, size=UPSTREAM_PAGE_SIZE)
            try:
                response = requests.post(page_url, headers=headers, json=payload, timeout=timeout)
            except RequestException as exc:
                raise AppException(
                    code=ErrorCode.TASK_FAILED,
                    message=f"客户端[{UPSTREAM_FILE_PAGE_PATH}]接口请求异常: {exc}",
                    status_code=502,
                ) from exc
            page_payload = self.extract_response_payload(response, path=UPSTREAM_FILE_PAGE_PATH)
            if not isinstance(page_payload, Mapping):
                logger.warning("接口分页响应不是对象: payload_type={}", type(page_payload).__name__)
                return all_records
            page_results = page_payload.get("results")
            if not isinstance(page_results, list):
                logger.warning("接口分页响应 results 字段不是列表: keys={}", list(page_payload.keys()))
                return all_records
            page_records = [row for row in page_results if isinstance(row, Mapping)]
            all_records.extend(page_records)
            logger.info(
                f"客户端分页查询完成: task_id={task.id}, 当前页={current}, 总页={len(page_records)}, 总加载数={len(all_records)}")
            total_pages = int(page_payload.get("totalCurrent") or 0)
            if total_pages <= 0 or current >= total_pages:
                return all_records
            current += 1

        logger.warning(
            f"客户端分页达到安全上限: task_id={task.id}, 最大分页={MAX_UPSTREAM_PAGE_COUNT}, 加载总数={len(all_records)}")
        return all_records

    def fetch_task_item_detail(self, session: Session, task: Task, task_item: TaskItem,
                               source_record: SourceTaskItemRecord) -> SourceTaskItemDetail:
        """按文件 ID 拉取单个上游文件的识别结果详情。"""
        client_api = ClientApi(session, task.client_id)
        auth_result = client_api.authenticate_client_model()
        headers = {"Authorization": auth_result.client.access_token}
        detail_url = ClientUtils.build_url(auth_result.client.api_url, UPSTREAM_FILE_DETAIL_PATH)
        file_id = source_record.file_id
        if not file_id:
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message="上游文件缺少 file_id，无法查询详情",
                status_code=502,
            )

        try:
            response = requests.get(
                detail_url,
                headers=headers,
                params={"fileId": file_id},
                timeout=get_settings().request_timeout_seconds,
            )
        except RequestException as exc:
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message=f"客户端[{UPSTREAM_FILE_DETAIL_PATH}]接口请求异常: {exc}",
                status_code=502,
            ) from exc
        detail_payload = self.extract_response_payload(response, path=UPSTREAM_FILE_DETAIL_PATH)
        if not isinstance(detail_payload, Mapping):
            logger.warning("接口详情响应不是对象: payload_type={}", type(detail_payload).__name__)
            return SourceTaskItemDetail(result_file_data="", record_data=[])
        record_data = detail_payload.get("recordData") or []
        if not isinstance(record_data, list):
            logger.warning(
                "上游详情 recordData 字段不是列表: payload_keys={} record_data_type={}",
                list(detail_payload.keys()),
                type(record_data).__name__,
            )
            record_data = []
        return SourceTaskItemDetail(
            result_file_data=str(detail_payload.get("resultFileData", "")),
            record_data=[row for row in record_data if isinstance(row, Mapping)],
        )


def build_upstream_file_download_url(client_api_url: str, file_name: str) -> str:
    """按客户端服务地址拼接文件下载地址。"""

    normalized_name = (file_name or "").strip().lstrip("/")
    parsed = urlparse(client_api_url)
    base_path = parsed.path.rstrip("/")
    if base_path.endswith("/api"):
        base_path = base_path[:-4]
    base_url = urlunparse(parsed._replace(path=f"{base_path}/", params="", query="", fragment=""))
    return urljoin(base_url, f"{FILE_DOWNLOAD_PATH_PREFIX.lstrip('/')}{normalized_name}")


def build_task_item_save_name(client: Any, source_record: SourceTaskItemRecord, extension: str) -> str:
    """按业务规则生成下载保存名。"""

    cleaned_parts: list[str] = []
    for part in (
        getattr(client, "tenant_name", ""),
        getattr(client, "tenant_code", ""),
        source_record.device_name,
        source_record.module,
        source_record.file_id,
        source_record.file_num,
        ID_TYPE_NAME_MAP.get(source_record.id_type, "未知"),
        CLASSIFY_NAME_MAP.get(source_record.classify, "未知"),
    ):
        text = str(part or "").strip()
        for char in ('/', "\\", ":", "*", "?", '"', "<", ">", "|"):
            text = text.replace(char, "_")
        cleaned_parts.append(text or "未知")

    extension_text = str(extension or "").strip()
    for char in ('/', "\\", ":", "*", "?", '"', "<", ">", "|"):
        extension_text = extension_text.replace(char, "_")
    return f"{'_'.join(cleaned_parts)}.{extension_text}"


class RequestsTaskFileDownloader:
    """通过 requests 下载任务文件。"""

    def download(self, session: Session, task: Task, task_item: TaskItem,
                 source_record: SourceTaskItemRecord) -> TaskDownloadResult:
        """下载原始文件和视频结果文件。"""

        item_dir = (
                get_settings().data_dir
                / "task_files"
                / str(task.id or 0)
                / str(task_item.id or 0)
        )
        item_dir.mkdir(parents=True, exist_ok=True)
        client = get_client_or_raise(session, task.client_id)
        original_path = item_dir / build_task_item_save_name(client, source_record, task_item.file_extension)
        self._download_url(
            build_upstream_file_download_url(client.api_url, task_item.file_url),
            original_path,
        )

        result_file_path: Path | None = None
        if task_item.file_bmp == 2 and task_item.result_file_data:
            result_file_path = item_dir / build_task_item_save_name(client, source_record, "datajson")
            self._download_url(
                build_upstream_file_download_url(client.api_url, task_item.result_file_data),
                result_file_path,
            )

        logger.info(
            "任务文件下载完成 task_id={} task_item_id={} file_path={} result_file_path={}",
            task.id,
            task_item.id,
            original_path,
            result_file_path,
        )
        return TaskDownloadResult(
            file_path=original_path.as_posix(),
            result_file_path=result_file_path.as_posix() if result_file_path else None,
        )

    def _download_url(self, url: str, target_path: Path) -> None:
        """下载单个 URL 到目标路径。"""

        try:
            response = requests.get(
                url,
                stream=True,
                timeout=get_settings().request_timeout_seconds,
            )
        except RequestException as exc:
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message=f"文件下载失败: {url}",
                status_code=502,
            ) from exc

        if response.status_code != 200:
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message=f"文件下载失败: HTTP {response.status_code}",
                status_code=502,
            )

        with target_path.open("wb") as file_obj:
            iter_content = getattr(response, "iter_content", None)
            if callable(iter_content):
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        file_obj.write(chunk)
            else:
                content = getattr(response, "content", b"")
                if isinstance(content, str):
                    content = content.encode()
                file_obj.write(content)

        close_func = getattr(response, "close", None)
        if callable(close_func):
            close_func()


class MultimodalTaskItemRecognizer:
    """基于已启用多模态模型的任务项识别器。"""

    def recognize(self, session: Session, task: Task, task_item: TaskItem,
                  data_rows: Sequence[TaskItemData]) -> Mapping[int, str]:
        """调用多模态模型并解析识别名称。"""

        model = self._get_default_multimodal_model(session)
        prompt = self._get_task_prompt(session, task.config_id)
        messages = [
            MultimodalChatMessagePayload(
                role="user",
                content=self._build_task_recognition_prompt(prompt, task_item, data_rows),
                attachments=self._build_task_item_attachments(task_item),
            )
        ]
        payload = build_gateway_chat_payload(
            model_name=model.model_name,
            messages=messages,
            stream=False,
        )
        result = call_chat_endpoint(
            endpoint_url=model.endpoint_url,
            api_key=model.api_key,
            payload=payload,
        )
        reply = extract_chat_reply(result.payload)
        if not reply:
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message="大模型未返回可解析的识别结果",
                status_code=502,
            )
        return self._parse_recognition_reply(reply, data_rows)

    @staticmethod
    def _get_default_multimodal_model(session: Session) -> MultimodalModel:
        """获取任务执行可用的默认多模态模型。"""

        model = session.exec(
            select(MultimodalModel)
            .where(MultimodalModel.status == "启用")
            .order_by(MultimodalModel.id)
        ).first()
        if model is None:
            raise AppException(
                code=ErrorCode.PARAMS_ERROR,
                message="没有启用的多模态模型配置，无法自动识别",
                status_code=400,
            )
        return model

    @staticmethod
    def _get_task_prompt(session: Session, config_id: int) -> str:
        """读取任务绑定的提示词。"""

        config = session.get(Config, config_id)
        if config is None or not config.text.strip():
            return "请识别附件中的目标，并返回识别名称。"
        return config.text.strip()

    @staticmethod
    def _build_task_recognition_prompt(prompt: str, task_item: TaskItem,
                                       data_rows: Sequence[TaskItemData]) -> str:
        """构造任务执行用大模型提示词。"""

        source_rows = [
            {
                "id": row.id or 0,
                "name": row.name,
                "trackIds": row.track_ids,
                "bbox": [row.minx, row.miny, row.maxx, row.maxy],
            }
            for row in data_rows
        ]
        return (
            f"{prompt}\n\n"
            "请根据附件内容复核下列原始识别结果，并只返回 JSON 数组。\n"
            "数组元素格式为 {\"id\": 任务明细ID, \"name\": \"识别名称\"}。\n"
            f"文件名：{task_item.name}\n"
            f"原始识别结果：{json.dumps(source_rows, ensure_ascii=False)}"
        )

    @classmethod
    def _build_task_item_attachments(cls, task_item: TaskItem) -> list[MultimodalAttachmentPayload]:
        """根据本地下载产物构造模型附件。"""

        attachments: list[MultimodalAttachmentPayload] = []
        file_path = Path(task_item.file_path) if task_item.file_path else None
        if task_item.file_bmp == 1 and file_path and file_path.exists():
            attachments.append(
                MultimodalAttachmentPayload(
                    name=file_path.name,
                    mimeType=mimetypes.guess_type(file_path.name)[0] or "image/jpeg",
                    kind="image",
                    dataUrl=cls._file_to_data_url(file_path),
                )
            )

        if task_item.file_bmp == 2:
            result_path = None
            if file_path:
                result_files = sorted(file_path.parent.glob("*.datajson"))
                result_path = result_files[0] if result_files else None
            text_content = ""
            if result_path and result_path.exists():
                text_content = result_path.read_text(encoding="utf-8")[:4000]
            attachments.append(
                MultimodalAttachmentPayload(
                    name=result_path.name if result_path else "result_file_data",
                    mimeType="application/json",
                    kind="document",
                    textContent=text_content or "视频任务未找到本地结果数据文件，请根据提示词和原始识别结果复核。",
                )
            )
        return attachments

    @staticmethod
    def _file_to_data_url(file_path: Path) -> str:
        """把本地文件编码为 data URL。"""

        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    @classmethod
    def _parse_recognition_reply(cls, reply: str, data_rows: Sequence[TaskItemData]) -> dict[int, str]:
        """解析大模型识别回复为 TaskItemData ID 到识别名称的映射。"""

        text = reply.strip()
        try:
            payload = json.loads(cls._extract_json_text(text))
        except json.JSONDecodeError:
            if len(data_rows) == 1 and text:
                return {data_rows[0].id or 0: text}
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message="大模型识别结果不是可解析 JSON",
                status_code=502,
            )

        rows = cls._extract_recognition_rows(payload)
        if not rows and len(data_rows) == 1:
            name = (
                payload.get("name", "")
                if isinstance(payload, Mapping)
                else ""
            )
            return {data_rows[0].id or 0: name} if name else {}

        result: dict[int, str] = {}
        source_by_id = {row.id or 0: row for row in data_rows}
        for index, row_payload in enumerate(rows):
            if not isinstance(row_payload, Mapping):
                continue
            row_id = row_payload.get("id", 0)
            if row_id == 0 and index < len(data_rows):
                row_id = data_rows[index].id or 0
            if row_id not in source_by_id:
                continue
            name = row_payload.get("name", "")
            if name:
                result[row_id] = name
        return result

    @staticmethod
    def _extract_json_text(text: str) -> str:
        """从模型回复中提取 JSON 文本。"""

        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        starts = [position for position in (text.find("["), text.find("{")) if position >= 0]
        if not starts:
            return text
        start = min(starts)
        end = max(text.rfind("]"), text.rfind("}"))
        return text[start:end + 1] if end >= start else text

    @staticmethod
    def _extract_recognition_rows(payload: Any) -> list[Mapping[str, Any]]:
        """从多种 JSON 结构中提取识别结果数组。"""

        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, Mapping)]
        if not isinstance(payload, Mapping):
            return []
        for key in ("results", "recordData", "record_data", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, Mapping)]
        return []


class TaskExecutionRunner:
    """编排单次 Task 执行流程。"""

    def __init__(self, session: Session, task_id: int,
                 downloader: TaskFileDownloader | None = None, recognizer: TaskItemRecognizer | None = None,
                 now: datetime | None = None) -> None:
        """初始化任务执行上下文。"""

        self.session = session
        self.task_id = task_id
        self._downloader = downloader
        self._recognizer = recognizer
        self.execution_now = now or datetime.now()
        task = self.session.get(Task, task_id)
        if task is None:
            raise AppException(code=ErrorCode.NOT_FOUND, message="任务不存在", status_code=404)
        self.task = task
        self.client = get_client_or_raise(self.session, self.task.client_id)
        self.source = AuthenticatedTaskExecutionSource()
        self.filters = TaskFiltersPayload()
        self.window = TaskExecutionWindow(start_at="", end_at="", should_fetch=False)
        self.inserted_items: list[tuple[TaskItem, SourceTaskItemRecord]] = []
        self.skipped_count = 0
        self.detail_row_count = 0

    @property
    def downloader(self) -> TaskFileDownloader:
        """返回本次执行使用的下载器。"""

        if self._downloader is None:
            self._downloader = RequestsTaskFileDownloader()
        return self._downloader

    @property
    def recognizer(self) -> TaskItemRecognizer:
        """返回本次执行使用的识别器。"""

        if self._recognizer is None:
            self._recognizer = MultimodalTaskItemRecognizer()
        return self._recognizer

    def run(self) -> TaskExecutionResult:
        """执行一次 Task 共享主干。"""

        logger.info(f"任务执行 开始1: task_id={self.task_id}, 执行模型={self.task.execution_mode}, "
                    f"自动确认={self.task.auto_confirm}, 活跃={self.task.active}")
        if is_task_running(self.task):
            self.task.skipped_count += 1
            self.task.updated_at = self.execution_now
            self.session.add(self.task)
            self.session.commit()
            logger.warning(f"任务执行 task_id={self.task_id} 正在运行，跳过本次重复触发")
            return TaskExecutionResult(
                task_id=self.task_id,
                inserted_count=0,
                skipped_count=1,
                detail_row_count=0,
                processed_count=self.task.processed_count,
                execution_status=self.task.execution_status,
            )

        if not self.task.filters_json:
            self.filters = TaskFiltersPayload()
        else:
            self.filters = TaskFiltersPayload.model_validate(json.loads(self.task.filters_json))
        end_at = clip_end_at(self.filters.end_at, self.execution_now)
        if self._is_auto_task(self.task):
            start_at = format_dt(self.task.last_pull_end_at) if self.task.last_pull_end_at else self.filters.start_at
            should_fetch = not (start_at and end_at and start_at >= end_at)
            self.window = TaskExecutionWindow(start_at=start_at, end_at=end_at, should_fetch=should_fetch)
        else:
            self.window = TaskExecutionWindow(start_at=self.filters.start_at, end_at=self.filters.end_at or end_at)
        logger.info(
            "任务执行 开始2 task_id={} 执行模型={} 开始时间={} 结束时间={} should_fetch={}",
            self.task_id,
            self.task.execution_mode,
            self.window.start_at,
            self.window.end_at,
            self.window.should_fetch,
        )

        self.task.started_at = self.execution_now
        self.task.last_run_started_at = self.execution_now
        self.task.finished_at = None
        self.task.last_error = None
        self.task.updated_at = self.execution_now
        self.session.add(self.task)
        self.session.commit()
        self.session.refresh(self.task)
        logger.info("任务执行 已初始化执行上下文 task_id={}", self.task_id)

        try:
            if self.window.should_fetch:
                source_records = [
                    SourceTaskItemRecord(
                        name=str(row.get("name", "")),
                        file_fid=str(row.get("fileFid", "")),
                        file_url=str(row.get("fileUrl", "")),
                        file_bmp=int(row.get("fileBmp") or 1),
                        file_id=str(row.get("id", "")),
                        device_name=str(row.get("deName", "")),
                        file_num=str(row.get("fileNum", "")),
                        file_extension=str(row.get("fileExtension", "")),
                        sp_name_list=str(row.get("spNameList", "")),
                        classify=int(row.get("classify") or 1),
                        module=str(row.get("module", "")),
                        id_type=int(row.get("idType") or 0),
                    )
                    for row in self.source.fetch_task_items(
                        session=self.session,
                        task=self.task,
                        filters=self.filters,
                        window=self.window,
                    )
                ]
                logger.info("任务执行 拉取taskItem完成 task_id={} 数量={}", self.task_id, len(source_records))
                self.inserted_items, self.skipped_count = self._insert_new_task_items(source_records)
                logger.info(
                    "任务执行 任务taskItem入库完成: task_id={}, 新增数量={}, 跳过数量={}",
                    self.task_id,
                    len(self.inserted_items),
                    self.skipped_count,
                )
                if self._is_auto_task(self.task):
                    self.task.last_pull_end_at = parse_window_end(self.window.end_at) or self.execution_now
            else:
                logger.info("任务执行 跳过拉取taskItem: task_id={}, 原因=empty_window", self.task_id)
            self.task.skipped_count += self.skipped_count

            for task_item, source_record in self.inserted_items:
                self.detail_row_count += self._insert_task_item_data_rows(task_item, source_record)
            logger.info(
                "任务执行 taskItemData入库完成 task_id={} 新增数量={} 详情数量={}",
                self.task_id,
                len(self.inserted_items),
                self.detail_row_count,
            )

            self.task.execution_status = TaskExecutionStatus.DOWN.value
            self.task.updated_at = self.execution_now
            self.session.add(self.task)
            self.session.commit()
            logger.info("任务执行 task进入下载阶段 task_id={} 新增数量={}", self.task_id, len(self.inserted_items))
            for task_item, source_record in self.inserted_items:
                self._download_task_item_file(task_item, source_record)

            self.task.execution_status = TaskExecutionStatus.LLM.value
            self.task.updated_at = self.execution_now
            self.session.add(self.task)
            self.session.commit()
            logger.info(
                "任务执行 task进入识别阶段 task_id={} 新增数量={} 跳过数量={}",
                self.task_id,
                len(self.inserted_items),
                self.skipped_count,
            )
            for task_item, _ in self.inserted_items:
                if task_item.down_state:
                    self._advance_task_item_recognition(task_item)
            self.task.execution_status = TaskExecutionStatus.FINISH.value
            self.task.finished_at = datetime.now()
            self.task.updated_at = self.task.finished_at
            self.task.total_count = len(
                self.session.exec(select(TaskItem.id).where(TaskItem.task_id == self.task_id)).all()
            )
            self.task.processed_count += len(self.inserted_items)
            self.session.add(self.task)
            self.session.commit()
            self.session.refresh(self.task)
            logger.info(
                "任务执行 task完成 task_id={} 新增Item数量={} 跳过数量={} 详情数量={} 处理数量={}",
                self.task_id,
                len(self.inserted_items),
                self.skipped_count,
                self.detail_row_count,
                self.task.processed_count,
            )
            return TaskExecutionResult(
                task_id=self.task_id,
                inserted_count=len(self.inserted_items),
                skipped_count=self.skipped_count,
                detail_row_count=self.detail_row_count,
                processed_count=self.task.processed_count,
                execution_status=self.task.execution_status,
            )
        except Exception as exc:
            task = self.session.get(Task, self.task_id)
            if task is not None:
                self.task = task
            self.task.execution_status = TaskExecutionStatus.FAIL.value
            self.task.last_error = str(exc)
            self.task.updated_at = datetime.now()
            self.session.add(self.task)
            self.session.commit()
            logger.exception(f"任务执行 task_id={self.task_id} 执行失败")
            raise

    def _insert_new_task_items(self, source_records: Sequence[SourceTaskItemRecord]) -> tuple[
        list[tuple[TaskItem, SourceTaskItemRecord]], int
    ]:
        """插入本次新发现的任务项，并跳过已存在的上游文件。"""

        if not source_records:
            return [], 0

        incoming_file_ids = [record.file_id for record in source_records if record.file_id]
        if len(incoming_file_ids) != len(source_records):
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message="上游分页数据缺少 id，无法按 file_id 去重",
                status_code=502,
            )

        existing_file_ids = set(
            self.session.exec(
                select(TaskItem.file_id).where(
                    TaskItem.task_id == self.task.id,
                    TaskItem.file_id.in_(incoming_file_ids),
                )
            ).all()
        )

        inserted: list[tuple[TaskItem, SourceTaskItemRecord]] = []
        skipped_count = 0
        for record in source_records:
            if record.file_id in existing_file_ids:
                skipped_count += 1
                continue

            task_item = TaskItem(
                task_id=self.task.id or 0,
                name=truncate(record.name, 200),
                device_name=truncate(record.device_name, 100),
                file_num=truncate(record.file_num, 50),
                file_extension=truncate(record.file_extension, 10),
                file_url=truncate(record.file_url, 200),
                file_id=truncate(record.file_id, 50),
                file_fid=truncate(record.file_fid, 50),
                sp_name_list=truncate(record.sp_name_list, 100),
                classify=record.classify,
                file_bmp=record.file_bmp,
                result_file_data="",
                id_type=record.id_type,
                status="created",
                created_at=self.execution_now,
                updated_at=self.execution_now,
                down_state=False,
                llm_state="pending",
                confirm_state="pending",
                remote_state="pending",
                train_state="pending",
            )
            self.session.add(task_item)
            self.session.commit()
            self.session.refresh(task_item)
            inserted.append((task_item, record))
            existing_file_ids.add(record.file_id)

        logger.debug(
            "taskItem落库完成 task_id={} 新增数量={} 跳过数量={}",
            self.task.id,
            len(inserted),
            skipped_count,
        )
        return inserted, skipped_count

    def _insert_task_item_data_rows(self, task_item: TaskItem, source_record: SourceTaskItemRecord) -> int:
        """拉取并插入单个任务项的识别明细行。"""

        detail = self.source.fetch_task_item_detail(
            session=self.session,
            task=self.task,
            task_item=task_item,
            source_record=source_record,
        )
        should_commit = False
        if detail.result_file_data:
            task_item.result_file_data = truncate(detail.result_file_data, 100)
            self.session.add(task_item)
            should_commit = True
        detail_rows = detail.record_data
        for row in detail_rows:
            task_item_data = TaskItemData(
                task_item_id=task_item.id or 0,
                name=truncate(str(row.get("name", "")), 100),
                score=float(row.get("score") or 0),
                track_ids=truncate(str(row.get("trackIds", "")), 100),
                sp_amount=int(row.get("spAmount") or 0),
                minx=optional_float(row.get("minx")),
                miny=optional_float(row.get("miny")),
                maxx=optional_float(row.get("maxx")),
                maxy=optional_float(row.get("maxy")),
                llm_name=None,
                status=TaskItemDataStatus.DEFAULT.value,
            )
            self.session.add(task_item_data)
            should_commit = True
        if should_commit:
            self.session.commit()
        logger.debug(
            "taskItemData落库完成 task_id={} task_item_id={} 数量={}",
            self.task.id,
            task_item.id,
            len(detail_rows),
        )
        return len(detail_rows)

    def _download_task_item_file(self, task_item: TaskItem, source_record: SourceTaskItemRecord) -> bool:
        """下载任务文件并更新 TaskItem 下载状态。"""

        task_item.status = "downloading"
        task_item.updated_at = self.execution_now
        self.session.add(task_item)
        self.session.commit()

        try:
            result = self.downloader.download(
                session=self.session,
                task=self.task,
                task_item=task_item,
                source_record=source_record,
            )
        except Exception as exc:  # noqa: BLE001
            task_item.down_state = False
            task_item.down_error = str(exc)
            task_item.status = "failed"
            task_item.updated_at = self.execution_now
            self.session.add(task_item)
            self.session.commit()
            logger.warning(
                "任务文件下载失败 task_id={} task_item_id={} error={}",
                self.task.id,
                task_item.id,
                exc,
            )
            return False

        task_item.down_state = True
        task_item.down_error = None
        task_item.file_path = result.file_path
        task_item.status = "downloaded"
        task_item.updated_at = self.execution_now
        self.session.add(task_item)
        self.session.commit()
        return True

    def _advance_task_item_recognition(self, task_item: TaskItem) -> None:
        """根据任务模式推进识别、确认、远端提交和训练状态。"""

        data_rows = self.session.exec(
            select(TaskItemData).where(TaskItemData.task_item_id == task_item.id)
        ).all()
        if self._is_auto_task(self.task):
            task_item.status = "llm"
            task_item.llm_state = "running"
            task_item.updated_at = self.execution_now
            self.session.add(task_item)
            self.session.commit()
            try:
                recognition_results = self.recognizer.recognize(
                    session=self.session,
                    task=self.task,
                    task_item=task_item,
                    data_rows=data_rows,
                )
                if data_rows and not recognition_results:
                    raise AppException(
                        code=ErrorCode.TASK_FAILED,
                        message="大模型未返回可匹配的识别结果",
                        status_code=502,
                    )
                self._apply_recognition_results(data_rows, recognition_results)
                task_item.llm_state = "success"
                task_item.llm_error = None
                task_item.llm_at = self.execution_now
                task_item.status = "verified"
            except Exception as exc:  # noqa: BLE001
                task_item.llm_state = "fail"
                task_item.llm_error = str(exc)
                task_item.llm_at = self.execution_now
                task_item.status = "failed"
                task_item.updated_at = self.execution_now
                self.session.add(task_item)
                self.session.commit()
                logger.warning(
                    "任务项大模型识别失败 task_id={} task_item_id={} error={}",
                    self.task.id,
                    task_item.id,
                    exc,
                )
                return
        else:
            task_item.llm_state = "pending"
            task_item.status = "downloaded"

        if self.task.auto_confirm and task_item.llm_state == "success":
            task_item.confirm_state = "auto_confirmed"
            task_item.confirmed_at = self.execution_now
            task_item.updated_at = self.execution_now
            self.session.add(task_item)
            self.session.commit()
            submit_task_item_outputs(self.session, task_item, now=self.execution_now)
        else:
            task_item.updated_at = self.execution_now
            self.session.add(task_item)
            self.session.commit()

    def _apply_recognition_results(self, data_rows: Sequence[TaskItemData],
                                   recognition_results: Mapping[int, str]) -> None:
        """把大模型识别结果写回 TaskItemData。"""

        normalized = {
            int(row_id): llm_name.strip()
            for row_id, llm_name in recognition_results.items()
            if llm_name and str(llm_name).strip()
        }
        for row in data_rows:
            row_id = row.id or 0
            llm_name = normalized.get(row_id)
            if llm_name is None:
                row.status = TaskItemDataStatus.DELETE.value
            else:
                row.llm_name = llm_name
                row.status = (
                    TaskItemDataStatus.DEFAULT.value
                    if llm_name.strip() == row.name.strip()
                    else TaskItemDataStatus.UPDATE.value
                )
            self.session.add(row)
        if data_rows:
            self.session.commit()

    @staticmethod
    def _is_auto_task(task: Task) -> bool:
        """判断任务是否采用自动执行模式。"""

        return task.execution_mode in {TaskExecutionMode.AUTO.value, "auto"}

def run_task_execution(session: Session, task_id: int,
                       downloader: TaskFileDownloader | None = None, recognizer: TaskItemRecognizer | None = None,
                       now: datetime | None = None) -> TaskExecutionResult:
    """执行一次 Task 共享主干。"""

    runner = TaskExecutionRunner(
        session=session,
        task_id=task_id,
        downloader=downloader,
        recognizer=recognizer,
        now=now,
    )
    return runner.run()


def is_task_running(task: Task) -> bool:
    """判断任务是否处于运行中状态。"""

    return task.execution_status in RUNNING_TASK_STATUSES
