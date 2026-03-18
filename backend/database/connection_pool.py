"""
连接池管理模块
提供MySQL数据库连接池管理功能
"""

# 确保环境变量已加载

import pymysql
from pymysql.cursors import DictCursor
from typing import Optional, Dict, Any
from contextlib import contextmanager
from queue import Queue, Empty, Full
import threading
import time
from backend.utils.logger import get_logger


logger = get_logger(__name__)


class ConnectionPool:
    """
    MySQL连接池管理器

    功能：
    1. 连接池管理（创建、获取、释放、关闭）
    2. 连接健康检查
    3. 连接自动回收
    4. 线程安全
    """

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_timeout: int = 30,
        pool_recycle: int = 3600,
        charset: str = "utf8mb4",
        **kwargs
    ):
        """
        初始化连接池

        Args:
            host: 数据库主机地址
            port: 数据库端口
            database: 数据库名称
            username: 数据库用户名
            password: 数据库密码
            pool_size: 连接池大小（核心连接数）
            max_overflow: 最大溢出连接数
            pool_timeout: 获取连接超时时间（秒）
            pool_recycle: 连接回收时间（秒）
            charset: 字符集
            **kwargs: 其他pymysql连接参数
        """
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_timeout = pool_timeout
        self.pool_recycle = pool_recycle
        self.charset = charset
        self.extra_kwargs = kwargs

        # 连接池队列
        self._pool: Queue = Queue(maxsize=pool_size + max_overflow)

        # 连接创建时间记录（用于回收）
        self._connection_times: Dict[int, float] = {}

        # 当前连接数统计
        self._current_connections = 0
        self._lock = threading.Lock()

        # 连接池状态
        self._closed = False

        # 初始化连接池
        self._initialize_pool()

        logger.info(
            f"ConnectionPool initialized: host={host}, port={port}, "
            f"database={database}, pool_size={pool_size}, max_overflow={max_overflow}"
        )

    def _initialize_pool(self):
        """初始化连接池，创建核心连接"""
        for _ in range(self.pool_size):
            try:
                conn = self._create_connection()
                self._pool.put(conn, block=False)
            except Exception as e:
                logger.error(f"Failed to initialize connection pool: {e}")
                raise

    def _create_connection(self) -> pymysql.Connection:
        """
        创建新的数据库连接

        Returns:
            数据库连接对象
        """
        try:
            conn = pymysql.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.username,
                password=self.password,
                charset=self.charset,
                cursorclass=DictCursor,
                autocommit=False,
                **self.extra_kwargs
            )

            # 记录连接创建时间
            conn_id = id(conn)
            self._connection_times[conn_id] = time.time()

            with self._lock:
                self._current_connections += 1

            logger.debug(f"Created new database connection: {conn_id}")
            return conn

        except Exception as e:
            logger.error(f"Failed to create database connection: {e}")
            raise

    def _is_connection_valid(self, conn: pymysql.Connection) -> bool:
        """
        检查连接是否有效

        Args:
            conn: 数据库连接对象

        Returns:
            连接是否有效
        """
        try:
            # 检查连接是否打开
            if not conn.open:
                return False

            # 执行ping检查连接
            conn.ping(reconnect=False)

            # 检查连接是否需要回收
            conn_id = id(conn)
            if conn_id in self._connection_times:
                create_time = self._connection_times[conn_id]
                if time.time() - create_time > self.pool_recycle:
                    logger.debug(f"Connection {conn_id} needs to be recycled")
                    return False

            return True

        except Exception as e:
            logger.debug(f"Connection validation failed: {e}")
            return False

    def _close_connection(self, conn: pymysql.Connection):
        """
        关闭数据库连接

        Args:
            conn: 数据库连接对象
        """
        try:
            conn_id = id(conn)
            conn.close()

            # 清理连接时间记录
            if conn_id in self._connection_times:
                del self._connection_times[conn_id]

            with self._lock:
                self._current_connections -= 1

            logger.debug(f"Closed database connection: {conn_id}")

        except Exception as e:
            logger.error(f"Failed to close connection: {e}")

    def get_connection(self, timeout: Optional[int] = None) -> pymysql.Connection:
        """
        从连接池获取连接

        Args:
            timeout: 超时时间（秒），None表示使用默认超时时间

        Returns:
            数据库连接对象

        Raises:
            Empty: 获取连接超时
            RuntimeError: 连接池已关闭
        """
        if self._closed:
            raise RuntimeError("Connection pool is closed")

        timeout = timeout or self.pool_timeout

        try:
            # 尝试从池中获取连接
            conn = self._pool.get(timeout=timeout)

            # 验证连接是否有效
            if not self._is_connection_valid(conn):
                logger.debug("Got invalid connection, creating new one")
                self._close_connection(conn)
                conn = self._create_connection()

            logger.debug(f"Got connection from pool: {id(conn)}")
            return conn

        except Empty:
            # 连接池为空，尝试创建新连接（如果未超过最大连接数）
            with self._lock:
                if self._current_connections < self.pool_size + self.max_overflow:
                    logger.debug("Pool empty, creating overflow connection")
                    return self._create_connection()

            # 超过最大连接数，抛出超时异常
            logger.error(f"Failed to get connection: timeout after {timeout}s")
            raise Empty(f"Failed to get connection from pool: timeout after {timeout}s")

    def return_connection(self, conn: pymysql.Connection):
        """
        归还连接到连接池

        Args:
            conn: 数据库连接对象
        """
        if self._closed:
            self._close_connection(conn)
            return

        try:
            # 回滚未提交的事务
            if conn.open:
                conn.rollback()

            # 验证连接是否有效
            if self._is_connection_valid(conn):
                # 归还到连接池
                try:
                    self._pool.put(conn, block=False)
                    logger.debug(f"Returned connection to pool: {id(conn)}")
                except Full:
                    # 连接池已满，关闭连接
                    logger.debug("Pool full, closing overflow connection")
                    self._close_connection(conn)
            else:
                # 连接无效，关闭连接
                logger.debug("Connection invalid, closing it")
                self._close_connection(conn)

        except Exception as e:
            logger.error(f"Failed to return connection: {e}")
            self._close_connection(conn)

    @contextmanager
    def connection(self, timeout: Optional[int] = None):
        """
        上下文管理器，自动获取和归还连接

        Args:
            timeout: 超时时间（秒）

        Yields:
            数据库连接对象

        Example:
            with pool.connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users")
        """
        conn = self.get_connection(timeout=timeout)
        try:
            yield conn
        finally:
            self.return_connection(conn)

    def close(self):
        """关闭连接池，释放所有连接"""
        if self._closed:
            return

        self._closed = True

        # 关闭所有连接
        while not self._pool.empty():
            try:
                conn = self._pool.get(block=False)
                self._close_connection(conn)
            except Empty:
                break

        try:
            logger.info("Connection pool closed")
        except Exception:
            pass

    def get_pool_status(self) -> Dict[str, Any]:
        """
        获取连接池状态信息

        Returns:
            连接池状态字典
        """
        return {
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "current_connections": self._current_connections,
            "available_connections": self._pool.qsize(),
            "in_use_connections": self._current_connections - self._pool.qsize(),
            "closed": self._closed,
        }

    def __repr__(self) -> str:
        status = self.get_pool_status()
        return (
            f"ConnectionPool(host='{self.host}', database='{self.database}', "
            f"current={status['current_connections']}, "
            f"available={status['available_connections']}, "
            f"in_use={status['in_use_connections']})"
        )

    def __del__(self):
        """析构函数，确保连接池被关闭"""
        try:
            self.close()
        except Exception:
            pass


# 全局连接池实例
_connection_pool: Optional[ConnectionPool] = None
_pool_lock = threading.Lock()

_DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
_DEFAULT_CONNECT_RETRY_TIMEOUT_SECONDS = 600
_DEFAULT_CONNECT_RETRY_INTERVAL_SECONDS = 5


def _parse_positive_int(value: Any, default: int) -> int:
    """将配置值解析为正整数，失败时返回默认值。"""
    try:
        parsed = int(value)
        if parsed <= 0:
            raise ValueError
        return parsed
    except (TypeError, ValueError):
        return default


def get_connection_pool(
    host: Optional[str] = None,
    port: Optional[int] = None,
    database: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    **kwargs
) -> ConnectionPool:
    """
    获取全局连接池实例（单例模式）

    Args:
        host: 数据库主机地址
        port: 数据库端口
        database: 数据库名称
        username: 数据库用户名
        password: 数据库密码
        **kwargs: 其他连接池参数

    Returns:
        ConnectionPool实例
    """
    global _connection_pool

    connect_timeout_seconds = _parse_positive_int(
        kwargs.get("connect_timeout"),
        _DEFAULT_CONNECT_TIMEOUT_SECONDS,
    )
    kwargs["connect_timeout"] = connect_timeout_seconds

    connect_retry_timeout_seconds = _parse_positive_int(
        kwargs.pop("connect_retry_timeout_seconds", _DEFAULT_CONNECT_RETRY_TIMEOUT_SECONDS),
        _DEFAULT_CONNECT_RETRY_TIMEOUT_SECONDS,
    )
    connect_retry_interval_seconds = _parse_positive_int(
        kwargs.pop("connect_retry_interval_seconds", _DEFAULT_CONNECT_RETRY_INTERVAL_SECONDS),
        _DEFAULT_CONNECT_RETRY_INTERVAL_SECONDS,
    )

    with _pool_lock:
        if _connection_pool is None:
            if not all([host, port, database, username, password]):
                raise ValueError(
                    "Database connection parameters are required for first initialization"
                )

            start_time = time.monotonic()
            attempt = 0

            while True:
                attempt += 1
                try:
                    _connection_pool = ConnectionPool(
                        host=host,
                        port=port,
                        database=database,
                        username=username,
                        password=password,
                        **kwargs
                    )
                    break
                except Exception as error:
                    elapsed_seconds = time.monotonic() - start_time
                    remaining_seconds = connect_retry_timeout_seconds - elapsed_seconds

                    if remaining_seconds <= 0:
                        logger.error(
                            "Database connection failed after %s attempts in %.1f seconds, giving up",
                            attempt,
                            elapsed_seconds,
                        )
                        raise RuntimeError(
                            f"Failed to connect to database within {connect_retry_timeout_seconds} seconds"
                        ) from error

                    sleep_seconds = min(connect_retry_interval_seconds, remaining_seconds)
                    logger.warning(
                        "Database connection attempt %s failed: %s. Retrying in %.1f seconds (%.1f seconds remaining)",
                        attempt,
                        error,
                        sleep_seconds,
                        remaining_seconds,
                    )
                    time.sleep(sleep_seconds)

        return _connection_pool


def close_connection_pool():
    """关闭全局连接池"""
    global _connection_pool

    with _pool_lock:
        if _connection_pool is not None:
            _connection_pool.close()
            _connection_pool = None
