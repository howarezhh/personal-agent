
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum
import uuid
import json

from backend.utils.time_utils import utc_now


class FileType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"
    TABULAR = "tabular"
    HTML = "html"
    IMAGE = "image"
    CODE = "code"
    TEXT = "text"
    MARKDOWN = "markdown"
    JSON = "json"
    XML = "xml"
    OTHER = "other"


class ProcessingStatus(str, Enum):
    PENDING = "pending"          # 等待处理
    PROCESSING = "processing"    # 处理中
    COMPLETED = "completed"      # 处理完成
    FAILED = "failed"            # 处理失败


@dataclass
class File:
    file_id: str
    user_id: str
    conversation_id: Optional[str]
    original_filename: str
    file_type: FileType
    file_size: int
    storage_path: str
    processing_status: ProcessingStatus
    created_at: datetime
    updated_at: datetime
    processed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    chunk_count: int = 0
    summary: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, data: dict) -> "File":
        payload = dict(data)

        for field_name in ("created_at", "updated_at", "processed_at"):
            field_value = payload.get(field_name)
            if isinstance(field_value, str):
                payload[field_name] = datetime.fromisoformat(field_value.replace("Z", "+00:00"))

        file_type = payload.get("file_type")
        if file_type is not None and not isinstance(file_type, FileType):
            payload["file_type"] = FileType(file_type)

        processing_status = payload.get("processing_status")
        if processing_status is not None and not isinstance(processing_status, ProcessingStatus):
            payload["processing_status"] = ProcessingStatus(processing_status)

        metadata = payload.get("metadata")
        if isinstance(metadata, str):
            try:
                payload["metadata"] = json.loads(metadata)
            except json.JSONDecodeError:
                payload["metadata"] = None

        return cls(**payload)

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "original_filename": self.original_filename,
            "file_type": self.file_type.value,  # 枚举转字符串
            "file_size": self.file_size,
            "storage_path": self.storage_path,
            "processing_status": self.processing_status.value,  # 枚举转字符串
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "error_message": self.error_message,
            "chunk_count": self.chunk_count,
            "summary": self.summary,
            "metadata": self.metadata
        }

    @staticmethod
    def from_db_row(row: tuple, columns: list) -> 'File':
        data = dict(zip(columns, row))
        return File.from_dict(data)


@dataclass
class FileCreate:
    user_id: str
    original_filename: str
    file_type: FileType
    file_size: int
    storage_path: str
    file_id: Optional[str] = None
    conversation_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def validate(self) -> tuple[bool, Optional[str]]:
        if not self.user_id:
            return False, "user_id不能为空"

        if not self.original_filename:
            return False, "original_filename不能为空"

        if not self.file_type:
            return False, "file_type不能为空"

        if self.file_size <= 0:
            return False, "file_size必须大于0"

        if not self.storage_path:
            return False, "storage_path不能为空"

        return True, None

    def to_file(self) -> File:
        now = utc_now()

        return File(
            file_id=self.file_id or str(uuid.uuid4()),
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            original_filename=self.original_filename,
            file_type=self.file_type,
            file_size=self.file_size,
            storage_path=self.storage_path,
            processing_status=ProcessingStatus.PENDING,
            created_at=now,
            updated_at=now,
            metadata=self.metadata
        )


@dataclass
class FileUpdate:
    processing_status: Optional[ProcessingStatus] = None
    processed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    chunk_count: Optional[int] = None
    summary: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        data = {}

        if self.processing_status is not None:
            data["processing_status"] = self.processing_status.value  # 枚举转字符串

        if self.processed_at is not None:
            data["processed_at"] = self.processed_at

        if self.error_message is not None:
            data["error_message"] = self.error_message

        if self.chunk_count is not None:
            data["chunk_count"] = self.chunk_count

        if self.summary is not None:
            data["summary"] = self.summary

        if self.metadata is not None:
            data["metadata"] = self.metadata

        # 总是更新updated_at
        data["updated_at"] = utc_now()

        return data


@dataclass
class FileChunk:
    chunk_id: str
    file_id: str
    chunk_index: int
    content: str
    page_number: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    token_count: Optional[int] = None
    vector_id: Optional[str] = None
    created_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "file_id": self.file_id,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "page_number": self.page_number,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "token_count": self.token_count,
            "vector_id": self.vector_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileChunk":
        # 处理datetime字段
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))

        # 处理metadata字段（如果是字符串，解析为字典）
        if isinstance(data.get("metadata"), str):
            try:
                data["metadata"] = json.loads(data["metadata"])
            except json.JSONDecodeError:
                data["metadata"] = None

        return cls(**data)

    @classmethod
    def from_db_row(cls, row: tuple, columns: list) -> "FileChunk":
        data = dict(zip(columns, row))
        return cls.from_dict(data)

    def set_metadata(self, key: str, value: Any):
        if self.metadata is None:
            self.metadata = {}
        self.metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        if self.metadata is None:
            return default
        return self.metadata.get(key, default)

    def get_char_range(self) -> Optional[tuple[int, int]]:
        if self.start_char is not None and self.end_char is not None:
            return (self.start_char, self.end_char)
        return None

    def get_content_preview(self, max_length: int = 100) -> str:
        if len(self.content) <= max_length:
            return self.content
        return self.content[:max_length] + "..."

    def __repr__(self) -> str:
        return f"FileChunk(chunk_id='{self.chunk_id}', file_id='{self.file_id}', index={self.chunk_index}, tokens={self.token_count})"
