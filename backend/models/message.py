"""
消息数据模型
对应数据库表: messages
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Literal
from datetime import datetime
import uuid
import json


MessageType = Literal["user", "assistant", "system"]


@dataclass
class Message:
    """
    消息数据模型

    对应数据库表: messages
    存储对话消息（用户消息和助手回复）
    """

    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str = ""
    message_type: MessageType = "user"
    content: str = ""
    sequence_number: int = 0
    parent_message_id: Optional[str] = None
    created_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        """
        转换为字典格式

        Returns:
            字典格式的消息数据
        """
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
        """
        从字典创建Message对象

        Args:
            data: 字典数据

        Returns:
            Message对象
        """
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
        """
        从数据库行创建Message对象

        Args:
            row: 数据库查询结果行
            columns: 列名列表

        Returns:
            Message对象
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

    def to_llm_format(self) -> dict:
        """
        转换为LLM调用格式

        Returns:
            LLM格式的消息字典 {"role": "user/assistant/system", "content": "..."}
        """
        return {
            "role": self.message_type,
            "content": self.content
        }

    def __repr__(self) -> str:
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"Message(message_id='{self.message_id}', type='{self.message_type}', content='{preview}')"


@dataclass
class MessageCreate:
    """
    创建消息的数据模型
    """

    conversation_id: str
    message_type: MessageType
    content: str
    sequence_number: int
    parent_message_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_message(self) -> Message:
        """
        转换为Message对象

        Returns:
            Message对象
        """
        return Message(
            conversation_id=self.conversation_id,
            message_type=self.message_type,
            content=self.content,
            sequence_number=self.sequence_number,
            parent_message_id=self.parent_message_id,
            metadata=self.metadata,
        )

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        验证消息数据

        Returns:
            (是否有效, 错误信息)
        """
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
    """
    更新消息的数据模型
    """

    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        """
        转换为字典格式（只包含非None的字段）

        Returns:
            字典格式的更新数据
        """
        data = {}
        if self.content is not None:
            data["content"] = self.content
        if self.metadata is not None:
            data["metadata"] = json.dumps(self.metadata, ensure_ascii=False)
        return data
