"""
JWT工具模块
提供JWT token的生成、验证和解析功能
"""

import jwt
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from backend.core.config_manager import get_config_manager
from backend.utils.logger import get_logger


logger = get_logger(__name__)


class JWTManager:
    """
    JWT管理器

    功能：
    1. 生成JWT token
    2. 验证JWT token
    3. 解析token获取用户信息
    4. 刷新token
    """

    def __init__(self):
        """初始化JWT管理器"""
        self.config_manager = get_config_manager()

        # 从配置中读取JWT配置
        jwt_config = self.config_manager.get_business_config("jwt")

        # JWT密钥（从环境变量读取，必须配置）
        self.secret_key = self.config_manager.get_with_env(
            "business.jwt.secret_key",
            "JWT_SECRET_KEY",
            None  # 不提供默认值，强制要求配置
        )

        # 验证密钥是否已配置
        if not self.secret_key or self.secret_key == "your-secret-key-change-in-production":
            error_msg = (
                "JWT密钥未配置！"
                "请设置JWT_SECRET_KEY环境变量或在配置文件中配置。"
                "生产环境中绝不能使用默认密钥！"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        # JWT算法
        self.algorithm = jwt_config.get("algorithm", "HS256")

        # Token过期时间
        # 支持两种配置方式：分钟或小时
        access_token_minutes = jwt_config.get("access_token_expire_minutes")
        if access_token_minutes:
            self.access_token_expire_hours = access_token_minutes / 60
        else:
            self.access_token_expire_hours = jwt_config.get("access_token_expire_hours", 24)

        self.refresh_token_expire_days = jwt_config.get("refresh_token_expire_days", 30)

        # Token发行者
        self.issuer = jwt_config.get("issuer", "personal-agent")

    def generate_access_token(
        self,
        user_id: str,
        username: str,
        additional_claims: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        生成访问token

        Args:
            user_id: 用户ID
            username: 用户名
            additional_claims: 额外的声明（可选）

        Returns:
            JWT token字符串
        """
        # 计算过期时间
        expire = datetime.utcnow() + timedelta(hours=self.access_token_expire_hours)

        # 构建payload
        payload = {
            "user_id": user_id,
            "username": username,
            "exp": expire,
            "iat": datetime.utcnow(),
            "iss": self.issuer,
            "type": "access"
        }

        # 添加额外的声明
        if additional_claims:
            payload.update(additional_claims)

        # 生成token
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

        logger.info(f"为用户生成访问令牌: {user_id}")
        return token

    def generate_refresh_token(
        self,
        user_id: str,
        username: str,
        additional_claims: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        生成刷新token

        Args:
            user_id: 用户ID
            username: 用户名

        Returns:
            JWT refresh token字符串
        """
        # 计算过期时间
        expire = datetime.utcnow() + timedelta(days=self.refresh_token_expire_days)

        # 构建payload
        payload = {
            "user_id": user_id,
            "username": username,
            "exp": expire,
            "iat": datetime.utcnow(),
            "iss": self.issuer,
            "type": "refresh",
            "jti": str(uuid4()),
        }

        if additional_claims:
            payload.update(additional_claims)

        # 生成token
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

        logger.info(f"为用户生成刷新令牌: {user_id}")
        return token

    def verify_token(self, token: str) -> tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        验证token

        Args:
            token: JWT token字符串

        Returns:
            (是否有效, payload字典, 错误信息)
        """
        try:
            # 解码并验证token
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                issuer=self.issuer
            )

            # 检查token类型
            token_type = payload.get("type")
            if token_type not in ["access", "refresh"]:
                return False, None, "无效的令牌类型"

            return True, payload, None

        except jwt.ExpiredSignatureError:
            logger.warning("令牌已过期")
            return False, None, "令牌已过期"

        except jwt.InvalidTokenError as e:
            logger.warning(f"无效的令牌: {str(e)}")
            return False, None, f"无效的令牌: {str(e)}"

        except Exception as e:
            logger.error(f"验证令牌失败: {str(e)}")
            return False, None, f"验证令牌失败: {str(e)}"

    def decode_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        解码token（不验证）

        Args:
            token: JWT token字符串

        Returns:
            payload字典，如果解码失败返回None
        """
        try:
            # 解码token（不验证签名）
            payload = jwt.decode(
                token,
                options={"verify_signature": False}
            )
            return payload

        except Exception as e:
            logger.error(f"解码令牌失败: {str(e)}")
            return None

    def get_user_id_from_token(self, token: str) -> Optional[str]:
        """
        从token中获取用户ID

        Args:
            token: JWT token字符串

        Returns:
            用户ID，如果获取失败返回None
        """
        is_valid, payload, error = self.verify_token(token)
        if is_valid and payload:
            return payload.get("user_id")
        return None

    def get_username_from_token(self, token: str) -> Optional[str]:
        """
        从token中获取用户名

        Args:
            token: JWT token字符串

        Returns:
            用户名，如果获取失败返回None
        """
        is_valid, payload, error = self.verify_token(token)
        if is_valid and payload:
            return payload.get("username")
        return None

    def refresh_access_token(self, refresh_token: str) -> Optional[str]:
        """
        使用刷新token生成新的访问token

        Args:
            refresh_token: 刷新token字符串

        Returns:
            新的访问token，如果刷新失败返回None
        """
        # 验证刷新token
        is_valid, payload, error = self.verify_token(refresh_token)

        if not is_valid or not payload:
            logger.warning(f"无效的刷新令牌: {error}")
            return None

        # 检查token类型
        if payload.get("type") != "refresh":
            logger.warning("令牌不是刷新令牌")
            return None

        # 生成新的访问token
        user_id = payload.get("user_id")
        username = payload.get("username")

        if not user_id or not username:
            logger.warning("刷新令牌中缺少用户标识或用户名")
            return None

        new_access_token = self.generate_access_token(user_id, username)
        logger.info(f"为用户刷新访问令牌: {user_id}")

        return new_access_token

    def get_token_expiration(self, token: str) -> Optional[datetime]:
        """
        获取token的过期时间

        Args:
            token: JWT token字符串

        Returns:
            过期时间，如果获取失败返回None
        """
        payload = self.decode_token(token)
        if payload and "exp" in payload:
            return datetime.fromtimestamp(payload["exp"])
        return None

    def is_token_expired(self, token: str) -> bool:
        """
        检查token是否已过期

        Args:
            token: JWT token字符串

        Returns:
            是否已过期
        """
        expiration = self.get_token_expiration(token)
        if expiration:
            return datetime.utcnow() > expiration
        return True


# 全局JWT管理器实例
_jwt_manager: Optional[JWTManager] = None


def get_jwt_manager() -> JWTManager:
    """
    获取全局JWT管理器实例（单例模式）

    Returns:
        JWTManager实例
    """
    global _jwt_manager

    if _jwt_manager is None:
        _jwt_manager = JWTManager()

    return _jwt_manager


# 便捷函数
def generate_token(user_id: str, username: str) -> str:
    """
    生成访问token（便捷函数）

    Args:
        user_id: 用户ID
        username: 用户名

    Returns:
        JWT token字符串
    """
    return get_jwt_manager().generate_access_token(user_id, username)


def verify_token(token: str) -> tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    验证token（便捷函数）

    Args:
        token: JWT token字符串

    Returns:
        (是否有效, payload字典, 错误信息)
    """
    return get_jwt_manager().verify_token(token)


def get_user_id_from_token(token: str) -> Optional[str]:
    """
    从token中获取用户ID（便捷函数）

    Args:
        token: JWT token字符串

    Returns:
        用户ID，如果获取失败返回None
    """
    return get_jwt_manager().get_user_id_from_token(token)
