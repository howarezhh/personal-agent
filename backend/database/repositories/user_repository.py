"""用户仓储模块。"""

from typing import Optional, List

from backend.database.database_manager import DatabaseManager, get_database_manager
from backend.models.user import User, UserUpdate
from backend.utils.logger import get_logger
from backend.utils.time_utils import utc_now


logger = get_logger(__name__)


class BaseRepository:
    """
    基础仓储类
    所有Repository都继承此类
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        """
        初始化仓储

        Args:
            db_manager: 数据库管理器实例，如果为None则使用全局实例
        """
        self.db = db_manager or get_database_manager()
        logger.debug(f"{self.__class__.__name__} initialized")

    def _dict_to_model(self, data: Optional[dict], model_class):
        """
        将字典转换为模型对象

        Args:
            data: 字典数据
            model_class: 模型类

        Returns:
            模型对象或None
        """
        if data is None:
            return None
        return model_class.from_dict(data)

    def _dicts_to_models(self, data_list: List[dict], model_class) -> List:
        """
        将字典列表转换为模型对象列表

        Args:
            data_list: 字典列表
            model_class: 模型类

        Returns:
            模型对象列表
        """
        return [model_class.from_dict(data) for data in data_list]


class UserRepository(BaseRepository):
    """
    用户仓储类

    功能：
    1. 用户CRUD操作
    2. 用户认证
    3. 用户查询
    """

    TABLE_NAME = "users"

    def create_user(self, user: User) -> User:
        """
        创建用户

        Args:
            user_create: 用户创建数据

        Returns:
            创建的用户对象

        Raises:
            ValueError: 数据验证失败
            Exception: 数据库操作失败
        """
        logger.info(f"[UserRepo] 开始创建用户: username={user.username}, email={user.email}")

        # 插入数据库
        data = {
            "user_id": user.user_id,
            "username": user.username,
            "email": user.email,
            "password_hash": user.password_hash,
            "full_name": user.full_name,
            "avatar_url": user.avatar_url,
            "is_active": user.is_active,
            "is_admin": user.is_admin,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
        }

        logger.debug(f"[UserRepo] 插入用户数据到数据库: user_id={user.user_id}")
        self.db.insert_one(self.TABLE_NAME, data, return_id=False)

        logger.info(f"[UserRepo] 用户创建成功: user_id={user.user_id}, username={user.username}")
        return user

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """
        根据用户ID获取用户

        Args:
            user_id: 用户ID

        Returns:
            用户对象，如果不存在返回None
        """
        result = self.db.select_one(
            table=self.TABLE_NAME,
            where={"user_id": user_id}
        )
        return self._dict_to_model(result, User)

    def get_user_by_username(self, username: str) -> Optional[User]:
        """
        根据用户名获取用户

        Args:
            username: 用户名

        Returns:
            用户对象，如果不存在返回None
        """
        result = self.db.select_one(
            table=self.TABLE_NAME,
            where={"username": username}
        )
        return self._dict_to_model(result, User)

    def get_user_by_email(self, email: str) -> Optional[User]:
        """
        根据邮箱获取用户

        Args:
            email: 邮箱

        Returns:
            用户对象，如果不存在返回None
        """
        result = self.db.select_one(
            table=self.TABLE_NAME,
            where={"email": email}
        )
        return self._dict_to_model(result, User)

    def update_user(self, user_id: str, user_update: UserUpdate) -> bool:
        """
        更新用户信息

        Args:
            user_id: 用户ID
            user_update: 用户更新数据

        Returns:
            是否更新成功

        Raises:
            ValueError: 用户不存在
            Exception: 数据库操作失败
        """
        # 检查用户是否存在
        if not self.exists_by_id(user_id):
            raise ValueError(f"用户不存在: user_id={user_id}")

        # 构建更新数据
        update_data = user_update.to_dict()
        if not update_data:
            return False

        # 添加更新时间
        update_data["updated_at"] = utc_now()

        # 执行更新
        affected_rows = self.db.update_one(
            table=self.TABLE_NAME,
            data=update_data,
            where={"user_id": user_id}
        )

        logger.info(f"User updated: user_id={user_id}, fields={list(update_data.keys())}")
        return affected_rows > 0

    def delete_user(self, user_id: str, soft_delete: bool = True) -> bool:
        """
        删除用户

        Args:
            user_id: 用户ID
            soft_delete: 是否软删除（默认True）

        Returns:
            是否删除成功

        Raises:
            ValueError: 用户不存在
            Exception: 数据库操作失败
        """
        # 检查用户是否存在
        if not self.exists_by_id(user_id):
            raise ValueError(f"用户不存在: user_id={user_id}")

        if soft_delete:
            # 软删除：设置is_active=False
            affected_rows = self.db.update_one(
                table=self.TABLE_NAME,
                data={"is_active": False, "updated_at": utc_now()},
                where={"user_id": user_id}
            )
            logger.info(f"User soft deleted: user_id={user_id}")
        else:
            # 硬删除：物理删除记录
            affected_rows = self.db.delete_one(
                table=self.TABLE_NAME,
                where={"user_id": user_id}
            )
            logger.info(f"User hard deleted: user_id={user_id}")

        return affected_rows > 0

    def update_last_login(self, user_id: str) -> bool:
        """
        更新用户最后登录时间

        Args:
            user_id: 用户ID

        Returns:
            是否更新成功
        """
        affected_rows = self.db.update_one(
            table=self.TABLE_NAME,
            data={"last_login_at": utc_now()},
            where={"user_id": user_id}
        )
        return affected_rows > 0

    def exists_by_id(self, user_id: str) -> bool:
        """
        检查用户ID是否存在

        Args:
            user_id: 用户ID

        Returns:
            是否存在
        """
        return self.db.exists(self.TABLE_NAME, {"user_id": user_id})

    def exists_by_username(self, username: str) -> bool:
        """
        检查用户名是否存在

        Args:
            username: 用户名

        Returns:
            是否存在
        """
        return self.db.exists(self.TABLE_NAME, {"username": username})

    def exists_by_email(self, email: str) -> bool:
        """
        检查邮箱是否存在

        Args:
            email: 邮箱

        Returns:
            是否存在
        """
        return self.db.exists(self.TABLE_NAME, {"email": email})

    def get_all_users(
        self,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        only_active: bool = True,
    ) -> List[User]:
        """
        获取所有用户

        Args:
            limit: 限制返回数量
            offset: 偏移量
            only_active: 是否只返回激活的用户

        Returns:
            用户列表
        """
        where = {"is_active": True} if only_active else None

        results = self.db.select_many(
            table=self.TABLE_NAME,
            where=where,
            order_by="created_at DESC",
            limit=limit,
            offset=offset,
        )

        return self._dicts_to_models(results, User)

    def count_users(self, only_active: bool = True) -> int:
        """
        统计用户数量

        Args:
            only_active: 是否只统计激活的用户

        Returns:
            用户数量
        """
        where = {"is_active": True} if only_active else None
        return self.db.count(self.TABLE_NAME, where)

# 全局用户仓储实例
_user_repository: Optional[UserRepository] = None


def get_user_repository() -> UserRepository:
    """
    获取全局用户仓储实例（单例模式）

    Returns:
        UserRepository实例
    """
    global _user_repository

    if _user_repository is None:
        _user_repository = UserRepository()

    return _user_repository
