
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime
import uuid
import json


@dataclass
class Conversation:
    conversation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    title: str = "新对话"
    description: Optional[str] = None
    is_active: bool = True
    message_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        # 格式化时间为ISO 8601格式，添加Z后缀表示UTC时间
        created_at_str = None
        updated_at_str = None
        if self.created_at:
            created_at_str = self.created_at.isoformat() + 'Z' if not self.created_at.isoformat().endswith('Z') else self.created_at.isoformat()
        if self.updated_at:
            updated_at_str = self.updated_at.isoformat() + 'Z' if not self.updated_at.isoformat().endswith('Z') else self.updated_at.isoformat()

        return {
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "title": self.title,
            "description": self.description,
            "is_active": self.is_active,
            "message_count": self.message_count,
            "created_at": created_at_str,
            "updated_at": updated_at_str,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Conversation":
        # 处理datetime字段
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
        if isinstance(data.get("updated_at"), str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))

        # 处理metadata字段（如果是字符串，解析为字典）
        if isinstance(data.get("metadata"), str):
            try:
                data["metadata"] = json.loads(data["metadata"])
            except json.JSONDecodeError:
                data["metadata"] = None

        return cls(**data)

    @classmethod
    def from_db_row(cls, row: tuple, columns: list) -> "Conversation":
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
        return f"Conversation(conversation_id='{self.conversation_id}', title='{self.title}', message_count={self.message_count})"


@dataclass
class ConversationCreate:
    user_id: str
    title: str = "新对话"
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_conversation(self) -> Conversation:
        return Conversation(
            user_id=self.user_id,
            title=self.title,
            description=self.description,
            metadata=self.metadata,
        )


@dataclass
class ConversationUpdate:
    title: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        data = {}
        if self.title is not None:
            data["title"] = self.title
        if self.description is not None:
            data["description"] = self.description
        if self.is_active is not None:
            data["is_active"] = self.is_active
        if self.metadata is not None:
            data["metadata"] = json.dumps(self.metadata, ensure_ascii=False)
        return data


@dataclass
class ConversationSummary:
    conversation_id: str
    title: str
    message_count: int
    updated_at: Optional[datetime]
    last_message_preview: Optional[str] = None

    def to_dict(self) -> dict:
        # 格式化时间为ISO 8601格式，添加Z后缀表示UTC时间
        updated_at_str = None
        if self.updated_at:
            updated_at_str = self.updated_at.isoformat() + 'Z' if not self.updated_at.isoformat().endswith('Z') else self.updated_at.isoformat()

        return {
            "conversation_id": self.conversation_id,
            "title": self.title,
            "message_count": self.message_count,
            "updated_at": updated_at_str,
            "last_message_preview": self.last_message_preview,
        }

    @classmethod
    def from_conversation(cls, conversation: Conversation, last_message_preview: Optional[str] = None) -> "ConversationSummary":
        return cls(
            conversation_id=conversation.conversation_id,
            title=conversation.title,
            message_count=conversation.message_count,
            updated_at=conversation.updated_at,
            last_message_preview=last_message_preview,
        )
