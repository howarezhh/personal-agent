"""
用户数据模型
对应数据库表: users
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
import uuid


@dataclass
class User:
    """
    用户数据模型

    对应数据库表: users
    存储用户基本信息
    """

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
        """
        转换为字典格式

        Returns:
            字典格式的用户数据
        """
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
        """
        转换为公开字典格式（不包含敏感信息）

        Returns:
            公开的用户数据字典
        """
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
        """
        从字典创建User对象

        Args:
            data: 字典数据

        Returns:
            User对象
        """
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
        """
        从数据库行创建User对象

        Args:
            row: 数据库查询结果行
            columns: 列名列表

        Returns:
            User对象
        """
        data = dict(zip(columns, row))
        return cls.from_dict(data)

    def __repr__(self) -> str:
        return f"User(user_id='{self.user_id}', username='{self.username}', email='{self.email}')"


@dataclass
class UserCreate:
    """
    创建用户的数据模型（用于注册）
    """

    username: str
    email: str
    password: str  # 明文密码，将在服务层进行哈希处理
    full_name: Optional[str] = None

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        验证用户输入数据

        Returns:
            (是否有效, 错误信息)
        """
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
    """
    更新用户的数据模型
    """

    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    email: Optional[str] = None

    def to_dict(self) -> dict:
        """
        转换为字典格式（只包含非None的字段）

        Returns:
            字典格式的更新数据
        """
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
    """
    用户登录的数据模型
    """

    username_or_email: str
    password: str

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        验证登录输入数据

        Returns:
            (是否有效, 错误信息)
        """
        if not self.username_or_email:
            return False, "请输入用户名或邮箱"
        if not self.password:
            return False, "请输入密码"
        return True, None
