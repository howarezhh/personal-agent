"""
会话数据模型
对应数据库表: conversations
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime
import uuid
import json


@dataclass
class Conversation:
    """
    会话数据模型

    对应数据库表: conversations
    存储用户的对话会话
    """

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
        """
        转换为字典格式

        Returns:
            字典格式的会话数据
        """
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
        """
        从字典创建Conversation对象

        Args:
            data: 字典数据

        Returns:
            Conversation对象
        """
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
        """
        从数据库行创建Conversation对象

        Args:
            row: 数据库查询结果行
            columns: 列名列表

        Returns:
            Conversation对象
        """
        data = dict(zip(columns, row))
        return cls.from_dict(data)

    def set_metadata(self, key: str, value: Any):
        """
        设置元数据

        Args:
            key: 元数据键
            value: 元数据值
        """
        if self.metadata is None:
            self.metadata = {}
        self.metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """
        获取元数据

        Args:
            key: 元数据键
            default: 默认值

        Returns:
            元数据值
        """
        if self.metadata is None:
            return default
        return self.metadata.get(key, default)

    def __repr__(self) -> str:
        return f"Conversation(conversation_id='{self.conversation_id}', title='{self.title}', message_count={self.message_count})"


@dataclass
class ConversationCreate:
    """
    创建会话的数据模型
    """

    user_id: str
    title: str = "新对话"
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_conversation(self) -> Conversation:
        """
        转换为Conversation对象

        Returns:
            Conversation对象
        """
        return Conversation(
            user_id=self.user_id,
            title=self.title,
            description=self.description,
            metadata=self.metadata,
        )


@dataclass
class ConversationUpdate:
    """
    更新会话的数据模型
    """

    title: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        """
        转换为字典格式（只包含非None的字段）

        Returns:
            字典格式的更新数据
        """
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
    """
    会话摘要数据模型（用于列表展示）
    """

    conversation_id: str
    title: str
    message_count: int
    updated_at: Optional[datetime]
    last_message_preview: Optional[str] = None

    def to_dict(self) -> dict:
        """
        转换为字典格式

        Returns:
            字典格式的会话摘要数据
        """
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
        """
        从Conversation对象创建ConversationSummary对象

        Args:
            conversation: Conversation对象
            last_message_preview: 最后一条消息的预览

        Returns:
            ConversationSummary对象
        """
        return cls(
            conversation_id=conversation.conversation_id,
            title=conversation.title,
            message_count=conversation.message_count,
            updated_at=conversation.updated_at,
            last_message_preview=last_message_preview,
        )
