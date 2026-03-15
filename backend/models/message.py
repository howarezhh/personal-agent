
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Literal
from datetime import datetime
import uuid
import json


MessageType = Literal["user", "assistant", "system"]


@dataclass
class Message:
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str = ""
    message_type: MessageType = "user"
    content: str = ""
    sequence_number: int = 0
    parent_message_id: Optional[str] = None
    created_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        # 格式化时间为ISO 8601格式，添加Z后缀表示UTC时间
        created_at_str = None
        if self.created_at:
            created_at_str = self.created_at.isoformat() + 'Z' if not self.created_at.isoformat().endswith('Z') else self.created_at.isoformat()

        return {
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "message_type": self.message_type,
            "content": self.content,
            "sequence_number": self.sequence_number,
            "parent_message_id": self.parent_message_id,
            "created_at": created_at_str,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
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
    def from_db_row(cls, row: tuple, columns: list) -> "Message":
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

    def to_llm_format(self) -> dict:
        return {
            "role": self.message_type,
            "content": self.content
        }

    def __repr__(self) -> str:
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"Message(message_id='{self.message_id}', type='{self.message_type}', content='{preview}')"


@dataclass
class MessageCreate:
    conversation_id: str
    message_type: MessageType
    content: str
    sequence_number: int
    parent_message_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_message(self) -> Message:
        return Message(
            conversation_id=self.conversation_id,
            message_type=self.message_type,
            content=self.content,
            sequence_number=self.sequence_number,
            parent_message_id=self.parent_message_id,
            metadata=self.metadata,
        )

    def validate(self) -> tuple[bool, Optional[str]]:
        if not self.conversation_id:
            return False, "会话ID不能为空"
        if not self.content:
            return False, "消息内容不能为空"
        if len(self.content) > 10000:
            return False, "消息内容不能超过10000个字符"
        if self.sequence_number < 1:
            return False, "消息序号必须大于0"
        return True, None


@dataclass
class MessageUpdate:
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        data = {}
        if self.content is not None:
            data["content"] = self.content
        if self.metadata is not None:
            data["metadata"] = json.dumps(self.metadata, ensure_ascii=False)
        return data
