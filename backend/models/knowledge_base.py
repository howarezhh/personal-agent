from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import uuid


@dataclass
class KnowledgeBase:
    knowledge_base_id: str
    user_id: str
    name: str
    description: Optional[str]
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict:
        return {
            'knowledge_base_id': self.knowledge_base_id,
            'user_id': self.user_id,
            'name': self.name,
            'description': self.description,
            'is_default': self.is_default,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'KnowledgeBase':
        return cls(
            knowledge_base_id=data['knowledge_base_id'],
            user_id=data['user_id'],
            name=data['name'],
            description=data.get('description'),
            is_default=bool(data.get('is_default', False)),
            is_active=bool(data.get('is_active', True)),
            created_at=data['created_at'],
            updated_at=data['updated_at'],
        )


@dataclass
class KnowledgeBaseCreate:
    user_id: str
    name: str
    description: Optional[str] = None
    knowledge_base_id: Optional[str] = None
    is_default: bool = False

    def validate(self) -> tuple[bool, Optional[str]]:
        if not self.user_id:
            return False, 'user_id不能为空'
        if not self.name or not self.name.strip():
            return False, '知识库名称不能为空'
        if len(self.name.strip()) > 100:
            return False, '知识库名称长度不能超过100个字符'
        if self.description and len(self.description) > 1000:
            return False, '知识库描述长度不能超过1000个字符'
        return True, None

    def to_knowledge_base(self) -> KnowledgeBase:
        now = datetime.utcnow()
        return KnowledgeBase(
            knowledge_base_id=self.knowledge_base_id or str(uuid.uuid4()),
            user_id=self.user_id,
            name=self.name.strip(),
            description=self.description.strip() if self.description else None,
            is_default=self.is_default,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
