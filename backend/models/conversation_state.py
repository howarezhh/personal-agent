
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime
import uuid

from backend.utils.time_utils import utc_now
import json


@dataclass
class ConversationState:
    state_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str = ""
    state_key: str = ""
    state_value: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
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
        data = dict(zip(columns, row))
        return cls.from_dict(data)

    def get_value(self, key: str, default: Any = None) -> Any:
        return self.state_value.get(key, default)

    def set_value(self, key: str, value: Any):
        self.state_value[key] = value
        self.updated_at = utc_now()

    def remove_value(self, key: str) -> bool:
        if key in self.state_value:
            del self.state_value[key]
            self.updated_at = utc_now()
            return True
        return False

    def clear_values(self):
        self.state_value = {}
        self.updated_at = utc_now()

    def __repr__(self) -> str:
        return f"ConversationState(state_id='{self.state_id}', conversation_id='{self.conversation_id}', key='{self.state_key}')"


@dataclass
class ConversationStateCreate:
    conversation_id: str
    state_key: str
    state_value: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> tuple[bool, Optional[str]]:
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
        now = utc_now()
        return ConversationState(
            conversation_id=self.conversation_id,
            state_key=self.state_key,
            state_value=self.state_value,
            created_at=now,
            updated_at=now,
        )


@dataclass
class ConversationStateUpdate:
    state_value: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        data = {}
        if self.state_value is not None:
            data["state_value"] = json.dumps(self.state_value, ensure_ascii=False)
        # 总是更新updated_at
        data["updated_at"] = utc_now()
        return data


@dataclass
class ConversationStateSummary:
    state_id: str
    conversation_id: str
    state_key: str
    value_count: int
    updated_at: Optional[datetime]

    def to_dict(self) -> dict:
        return {
            "state_id": self.state_id,
            "conversation_id": self.conversation_id,
            "state_key": self.state_key,
            "value_count": self.value_count,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_conversation_state(cls, state: ConversationState) -> "ConversationStateSummary":
        return cls(
            state_id=state.state_id,
            conversation_id=state.conversation_id,
            state_key=state.state_key,
            value_count=len(state.state_value) if state.state_value else 0,
            updated_at=state.updated_at,
        )
