
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime
import uuid
import json


@dataclass
class RetrievalResult:
    result_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    execution_id: str = ""
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    source_name: Optional[str] = None
    content: str = ""
    relevance_score: Optional[float] = None
    rank: Optional[int] = None
    created_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        return {
            "result_id": self.result_id,
            "execution_id": self.execution_id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "content": self.content,
            "relevance_score": self.relevance_score,
            "rank": self.rank,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RetrievalResult":
        normalized = dict(data)

        if "rank" not in normalized and "rank_position" in normalized:
            normalized["rank"] = normalized.pop("rank_position")
        else:
            normalized.pop("rank_position", None)

        # 处理datetime字段
        if isinstance(normalized.get("created_at"), str):
            normalized["created_at"] = datetime.fromisoformat(normalized["created_at"].replace("Z", "+00:00"))

        # 处理metadata字段（如果是字符串，解析为字典）
        if isinstance(normalized.get("metadata"), str):
            try:
                normalized["metadata"] = json.loads(normalized["metadata"])
            except json.JSONDecodeError:
                normalized["metadata"] = None

        if not normalized.get("source_name") and isinstance(normalized.get("metadata"), dict):
            normalized["source_name"] = normalized["metadata"].get("source")

        return cls(**normalized)

    @classmethod
    def from_db_row(cls, row: tuple, columns: list) -> "RetrievalResult":
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

    def __repr__(self) -> str:
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"RetrievalResult(result_id='{self.result_id}', source='{self.source_name}', score={self.relevance_score})"


@dataclass
class RetrievalResultCreate:
    execution_id: str
    content: str
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    source_name: Optional[str] = None
    relevance_score: Optional[float] = None
    rank: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_retrieval_result(self) -> RetrievalResult:
        return RetrievalResult(
            execution_id=self.execution_id,
            source_type=self.source_type,
            source_id=self.source_id,
            source_name=self.source_name,
            content=self.content,
            relevance_score=self.relevance_score,
            rank=self.rank,
            metadata=self.metadata,
        )

    def validate(self) -> tuple[bool, Optional[str]]:
        if not self.execution_id:
            return False, "执行ID不能为空"
        if not self.content:
            return False, "检索内容不能为空"
        if self.relevance_score is not None and (self.relevance_score < 0 or self.relevance_score > 1):
            return False, "相关度分数必须在0-1之间"
        if self.rank is not None and self.rank < 1:
            return False, "排名必须大于0"
        return True, None


@dataclass
class RetrievalResultSummary:
    result_id: str
    source_name: Optional[str]
    content_preview: str
    relevance_score: Optional[float]
    rank: Optional[int]

    def to_dict(self) -> dict:
        return {
            "result_id": self.result_id,
            "source_name": self.source_name,
            "content_preview": self.content_preview,
            "relevance_score": self.relevance_score,
            "rank": self.rank,
        }

    @classmethod
    def from_retrieval_result(cls, result: RetrievalResult, preview_length: int = 200) -> "RetrievalResultSummary":
        content_preview = result.content[:preview_length]
        if len(result.content) > preview_length:
            content_preview += "..."

        return cls(
            result_id=result.result_id,
            source_name=result.source_name,
            content_preview=content_preview,
            relevance_score=result.relevance_score,
            rank=result.rank,
        )
