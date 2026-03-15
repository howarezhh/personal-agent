
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
import uuid


@dataclass
class User:
    user_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    username: str = ""
    email: str = ""
    password_hash: str = ""
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: bool = True
    is_admin: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "password_hash": self.password_hash,
            "full_name": self.full_name,
            "avatar_url": self.avatar_url,
            "is_active": self.is_active,
            "is_admin": self.is_admin,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }

    def to_public_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "avatar_url": self.avatar_url,
            "is_active": self.is_active,
            "is_admin": self.is_admin,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        # 处理datetime字段
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
        if isinstance(data.get("updated_at"), str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
        if isinstance(data.get("last_login_at"), str):
            data["last_login_at"] = datetime.fromisoformat(data["last_login_at"].replace("Z", "+00:00"))

        return cls(**data)

    @classmethod
    def from_db_row(cls, row: tuple, columns: list) -> "User":
        data = dict(zip(columns, row))
        return cls.from_dict(data)

    def __repr__(self) -> str:
        return f"User(user_id='{self.user_id}', username='{self.username}', email='{self.email}')"


@dataclass
class UserCreate:
    username: str
    email: str
    password: str  # 明文密码，将在服务层进行哈希处理
    full_name: Optional[str] = None

    def validate(self) -> tuple[bool, Optional[str]]:
        # 验证用户名
        if not self.username or len(self.username) < 3:
            return False, "用户名至少需要3个字符"
        if len(self.username) > 50:
            return False, "用户名不能超过50个字符"

        # 验证邮箱
        if not self.email or "@" not in self.email:
            return False, "邮箱格式不正确"
        if len(self.email) > 100:
            return False, "邮箱不能超过100个字符"

        # 验证密码
        if not self.password or len(self.password) < 8:
            return False, "密码至少需要8个字符"
        if len(self.password) > 100:
            return False, "密码不能超过100个字符"

        # 密码强度检查：至少包含字母和数字
        has_letter = any(c.isalpha() for c in self.password)
        has_digit = any(c.isdigit() for c in self.password)
        if not (has_letter and has_digit):
            return False, "密码必须包含字母和数字"

        return True, None


@dataclass
class UserUpdate:
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    email: Optional[str] = None

    def to_dict(self) -> dict:
        data = {}
        if self.full_name is not None:
            data["full_name"] = self.full_name
        if self.avatar_url is not None:
            data["avatar_url"] = self.avatar_url
        if self.email is not None:
            data["email"] = self.email
        return data


@dataclass
class UserLogin:
    username_or_email: str
    password: str

    def validate(self) -> tuple[bool, Optional[str]]:
        if not self.username_or_email:
            return False, "请输入用户名或邮箱"
        if not self.password:
            return False, "请输入密码"
        return True, None
