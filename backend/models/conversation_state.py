"""
会话状态数据模型
对应数据库表: conversation_states
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime
import uuid
import json


@dataclass
class ConversationState:
    """
    会话状态数据模型

    对应数据库表: conversation_states
    存储会话的状态信息，用于复杂对话流程
    """

    state_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str = ""
    state_key: str = ""
    state_value: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """
        转换为字典格式

        Returns:
            字典格式的会话状态数据
        """
        return {
            "state_id": self.state_id,
            "conversation_id": self.conversation_id,
            "state_key": self.state_key,
            "state_value": self.state_value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationState":
        """
        从字典创建ConversationState对象

        Args:
            data: 字典数据

        Returns:
            ConversationState对象
        """
        # 处理datetime字段
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
        if isinstance(data.get("updated_at"), str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))

        # 处理state_value字段（如果是字符串，解析为字典）
        if isinstance(data.get("state_value"), str):
            try:
                data["state_value"] = json.loads(data["state_value"])
            except json.JSONDecodeError:
                data["state_value"] = {}

        return cls(**data)

    @classmethod
    def from_db_row(cls, row: tuple, columns: list) -> "ConversationState":
        """
        从数据库行创建ConversationState对象

        Args:
            row: 数据库查询结果行
            columns: 列名列表

        Returns:
            ConversationState对象
        """
        data = dict(zip(columns, row))
        return cls.from_dict(data)

    def get_value(self, key: str, default: Any = None) -> Any:
        """
        从state_value中获取指定键的值

        Args:
            key: 键名
            default: 默认值

        Returns:
            键对应的值
        """
        return self.state_value.get(key, default)

    def set_value(self, key: str, value: Any):
        """
        在state_value中设置键值对

        Args:
            key: 键名
            value: 值
        """
        self.state_value[key] = value
        self.updated_at = datetime.utcnow()

    def remove_value(self, key: str) -> bool:
        """
        从state_value中移除指定键

        Args:
            key: 键名

        Returns:
            是否成功移除
        """
        if key in self.state_value:
            del self.state_value[key]
            self.updated_at = datetime.utcnow()
            return True
        return False

    def clear_values(self):
        """
        清空state_value中的所有值
        """
        self.state_value = {}
        self.updated_at = datetime.utcnow()

    def __repr__(self) -> str:
        return f"ConversationState(state_id='{self.state_id}', conversation_id='{self.conversation_id}', key='{self.state_key}')"


@dataclass
class ConversationStateCreate:
    """
    创建会话状态的数据模型
    """

    conversation_id: str
    state_key: str
    state_value: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        验证会话状态数据

        Returns:
            (是否有效, 错误信息)
        """
        if not self.conversation_id:
            return False, "会话ID不能为空"
        if not self.state_key:
            return False, "状态键不能为空"
        if len(self.state_key) > 100:
            return False, "状态键长度不能超过100个字符"
        if not isinstance(self.state_value, dict):
            return False, "状态值必须是字典类型"
        return True, None

    def to_conversation_state(self) -> ConversationState:
        """
        转换为ConversationState对象

        Returns:
            ConversationState对象
        """
        now = datetime.utcnow()
        return ConversationState(
            conversation_id=self.conversation_id,
            state_key=self.state_key,
            state_value=self.state_value,
            created_at=now,
            updated_at=now,
        )


@dataclass
class ConversationStateUpdate:
    """
    更新会话状态的数据模型
    """

    state_value: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        """
        转换为字典格式（只包含非None的字段）

        Returns:
            字典格式的更新数据
        """
        data = {}
        if self.state_value is not None:
            data["state_value"] = json.dumps(self.state_value, ensure_ascii=False)
        # 总是更新updated_at
        data["updated_at"] = datetime.utcnow()
        return data


@dataclass
class ConversationStateSummary:
    """
    会话状态摘要数据模型（用于展示）
    """

    state_id: str
    conversation_id: str
    state_key: str
    value_count: int
    updated_at: Optional[datetime]

    def to_dict(self) -> dict:
        """
        转换为字典格式

        Returns:
            字典格式的会话状态摘要数据
        """
        return {
            "state_id": self.state_id,
            "conversation_id": self.conversation_id,
            "state_key": self.state_key,
            "value_count": self.value_count,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_conversation_state(cls, state: ConversationState) -> "ConversationStateSummary":
        """
        从ConversationState对象创建ConversationStateSummary对象

        Args:
            state: ConversationState对象

        Returns:
            ConversationStateSummary对象
        """
        return cls(
            state_id=state.state_id,
            conversation_id=state.conversation_id,
            state_key=state.state_key,
            value_count=len(state.state_value) if state.state_value else 0,
            updated_at=state.updated_at,
        )
