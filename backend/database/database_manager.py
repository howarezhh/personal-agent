"""
数据库管理模块
提供统一的数据库操作接口
"""

# 确保环境变量已加载
from backend.core.env_loader import load_environment
load_environment()

import pymysql
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager
import time
from backend.database.connection_pool import ConnectionPool, get_connection_pool
from backend.core.config_manager import get_config_manager
from backend.utils.logger import get_logger, log_database_operation


logger = get_logger(__name__)


class DatabaseManager:
    """
    数据库管理器

    功能：
    1. 连接池管理
    2. 统一的CRUD操作接口
    3. 事务管理
    4. 错误处理和重试机制
    5. 日志记录
    """

    def __init__(self, connection_pool: Optional[ConnectionPool] = None):
        """
        初始化数据库管理器

        Args:
            connection_pool: 连接池实例，如果为None则从配置创建
        """
        if connection_pool is None:
            # 从配置管理器读取数据库配置
            config_manager = get_config_manager()
            db_config = config_manager.get_database_config("mysql")

            # 创建连接池
            connection_pool = get_connection_pool(
                host=db_config.get("host", "localhost"),
                port=db_config.get("port", 3306),
                database=db_config.get("database", "personal_agent"),
                username=db_config.get("username", "root"),
                password=db_config.get("password", ""),
                pool_size=db_config.get("pool_size", 10),
                max_overflow=db_config.get("max_overflow", 20),
                pool_timeout=db_config.get("pool_timeout", 30),
                pool_recycle=db_config.get("pool_recycle", 3600),
                charset=db_config.get("charset", "utf8mb4"),
                connect_timeout=db_config.get("connect_timeout", 10),
                connect_retry_timeout_seconds=db_config.get("connect_retry_timeout_seconds", 600),
                connect_retry_interval_seconds=db_config.get("connect_retry_interval_seconds", 5),
            )

        self.pool = connection_pool
        logger.info("DatabaseManager initialized")

    @contextmanager
    def get_connection(self):
        """
        获取数据库连接（上下文管理器）

        Yields:
            数据库连接对象
        """
        with self.pool.connection() as conn:
            yield conn

    @contextmanager # 装饰器：将下面的生成器函数转为上下文管理器
    def transaction(self):
        """
        事务上下文管理器

        Yields:
            数据库连接对象

        Example:
            with db_manager.transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO users ...")
                cursor.execute("INSERT INTO conversations ...")
                # 自动提交或回滚
        """
        conn = self.pool.get_connection()
        try:
            # 2. 暂停执行，将conn返回给with块中的变量（as conn）
            # 此时开始执行with块内的业务代码（比如insert/update）
            yield conn

            # 3. with块代码执行成功后，执行这里（无异常则提交事务）
            conn.commit()
            logger.debug("Transaction committed")

        except Exception as e:
            # 4. with块代码抛出异常时，执行这里（回滚事务）
            conn.rollback()
            logger.error(f"Transaction rolled back: {e}")
            raise  # 重新抛出异常，让调用方感知

        finally:
            # 5. 无论是否异常，最终都会归还连接（关键：避免连接泄露）
            self.pool.return_connection(conn)

    def execute_query(
        self,
        sql: str,
        params: Optional[Tuple] = None,
        fetch_one: bool = False,
        fetch_all: bool = True,
        retry_count: int = 3,
    ) -> Optional[Any]:
        """
        执行查询SQL（SELECT）

        Args:
            sql: SQL语句
            params: SQL参数
            fetch_one: 是否只获取一条记录
            fetch_all: 是否获取所有记录
            retry_count: 重试次数

        Returns:
            查询结果（字典或字典列表）

        Raises:
            Exception: 数据库操作失败
        """
        start_time = time.time()
        last_error = None

        for attempt in range(retry_count):
            try:
                with self.get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(sql, params or ())

                        if fetch_one:
                            result = cursor.fetchone()
                        elif fetch_all:
                            result = cursor.fetchall()
                        else:
                            result = None

                        execution_time_ms = (time.time() - start_time) * 1000

                        # 记录日志
                        log_database_operation(
                            logger=logger,
                            operation="SELECT",
                            table=self._extract_table_name(sql),
                            success=True,
                            execution_time_ms=execution_time_ms,
                            rows_affected=len(result) if result else 0,
                        )

                        return result

            except Exception as e:
                last_error = e
                logger.warning(
                    f"Query execution failed (attempt {attempt + 1}/{retry_count}): {e}"
                )
                if attempt < retry_count - 1:
                    time.sleep(0.1 * (attempt + 1))  # 指数退避
                continue

        # 所有重试都失败
        execution_time_ms = (time.time() - start_time) * 1000
        log_database_operation(
            logger=logger,
            operation="SELECT",
            table=self._extract_table_name(sql),
            success=False,
            execution_time_ms=execution_time_ms,
            error=str(last_error),
        )
        raise last_error

    def execute_update(
        self,
        sql: str,
        params: Optional[Tuple] = None,
        retry_count: int = 3,
    ) -> int:
        """
        执行更新SQL（INSERT/UPDATE/DELETE）

        Args:
            sql: SQL语句
            params: SQL参数
            retry_count: 重试次数

        Returns:
            影响的行数

        Raises:
            Exception: 数据库操作失败
        """
        start_time = time.time()
        last_error = None
        operation = self._extract_operation(sql)

        for attempt in range(retry_count):
            try:
                with self.transaction() as conn:
                    with conn.cursor() as cursor:
                        affected_rows = cursor.execute(sql, params or ())

                        execution_time_ms = (time.time() - start_time) * 1000

                        # 记录日志
                        log_database_operation(
                            logger=logger,
                            operation=operation,
                            table=self._extract_table_name(sql),
                            success=True,
                            execution_time_ms=execution_time_ms,
                            rows_affected=affected_rows,
                        )

                        return affected_rows

            except Exception as e:
                last_error = e
                logger.warning(
                    f"Update execution failed (attempt {attempt + 1}/{retry_count}): {e}"
                )
                if attempt < retry_count - 1:
                    time.sleep(0.1 * (attempt + 1))  # 指数退避
                continue

        # 所有重试都失败
        execution_time_ms = (time.time() - start_time) * 1000
        log_database_operation(
            logger=logger,
            operation=operation,
            table=self._extract_table_name(sql),
            success=False,
            execution_time_ms=execution_time_ms,
            error=str(last_error),
        )
        raise last_error

    def execute_many(
        self,
        sql: str,
        params_list: List[Tuple],
        retry_count: int = 3,
    ) -> int:
        """
        批量执行SQL

        Args:
            sql: SQL语句
            params_list: 参数列表
            retry_count: 重试次数

        Returns:
            影响的总行数

        Raises:
            Exception: 数据库操作失败
        """
        start_time = time.time()
        last_error = None
        operation = self._extract_operation(sql)

        for attempt in range(retry_count):
            try:
                with self.transaction() as conn:
                    with conn.cursor() as cursor:
                        affected_rows = cursor.executemany(sql, params_list)

                        execution_time_ms = (time.time() - start_time) * 1000

                        # 记录日志
                        log_database_operation(
                            logger=logger,
                            operation=f"{operation}_MANY",
                            table=self._extract_table_name(sql),
                            success=True,
                            execution_time_ms=execution_time_ms,
                            rows_affected=affected_rows,
                            batch_size=len(params_list),
                        )

                        return affected_rows

            except Exception as e:
                last_error = e
                logger.warning(
                    f"Batch execution failed (attempt {attempt + 1}/{retry_count}): {e}"
                )
                if attempt < retry_count - 1:
                    time.sleep(0.1 * (attempt + 1))  # 指数退避
                continue

        # 所有重试都失败
        execution_time_ms = (time.time() - start_time) * 1000
        log_database_operation(
            logger=logger,
            operation=f"{operation}_MANY",
            table=self._extract_table_name(sql),
            success=False,
            execution_time_ms=execution_time_ms,
            error=str(last_error),
        )
        raise last_error

    def insert_one(
        self,
        table: str,
        data: Dict[str, Any],
        return_id: bool = True,
    ) -> Optional[int]:
        """
        插入单条记录

        Args:
            table: 表名
            data: 数据字典
            return_id: 是否返回插入的ID

        Returns:
            插入的记录ID（如果return_id=True）

        Raises:
            Exception: 数据库操作失败
        """
        if not data:
            raise ValueError("Data cannot be empty")

        columns = list(data.keys())
        placeholders = ["%s"] * len(columns)

        sql = f"""
            INSERT INTO {table} ({', '.join(columns)})
            VALUES ({', '.join(placeholders)})
        """

        params = tuple(data[col] for col in columns)

        start_time = time.time()

        try:
            with self.transaction() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    inserted_id = cursor.lastrowid if return_id else None

                    execution_time_ms = (time.time() - start_time) * 1000

                    # 记录日志
                    log_database_operation(
                        logger=logger,
                        operation="INSERT",
                        table=table,
                        success=True,
                        execution_time_ms=execution_time_ms,
                        rows_affected=1,
                    )

                    return inserted_id

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            log_database_operation(
                logger=logger,
                operation="INSERT",
                table=table,
                success=False,
                execution_time_ms=execution_time_ms,
                error=str(e),
            )
            raise

    def update_one(
        self,
        table: str,
        data: Dict[str, Any],
        where: Dict[str, Any],
    ) -> int:
        """
        更新单条记录

        Args:
            table: 表名
            data: 更新的数据字典
            where: WHERE条件字典

        Returns:
            影响的行数

        Raises:
            Exception: 数据库操作失败
        """
        if not data:
            raise ValueError("Data cannot be empty")
        if not where:
            raise ValueError("WHERE condition cannot be empty")

        set_clause = ", ".join([f"{col} = %s" for col in data.keys()])
        where_clause = " AND ".join([f"{col} = %s" for col in where.keys()])

        sql = f"""
            UPDATE {table}
            SET {set_clause}
            WHERE {where_clause}
        """

        params = tuple(list(data.values()) + list(where.values()))

        return self.execute_update(sql, params)

    def delete_one(
        self,
        table: str,
        where: Dict[str, Any],
    ) -> int:
        """
        删除记录

        Args:
            table: 表名
            where: WHERE条件字典

        Returns:
            影响的行数

        Raises:
            Exception: 数据库操作失败
        """
        if not where:
            raise ValueError("WHERE condition cannot be empty")

        where_clause = " AND ".join([f"{col} = %s" for col in where.keys()])

        sql = f"""
            DELETE FROM {table}
            WHERE {where_clause}
        """

        params = tuple(where.values())

        return self.execute_update(sql, params)

    def select_one(
        self,
        table: str,
        columns: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        查询单条记录

        Args:
            table: 表名
            columns: 查询的列名列表，None表示查询所有列
            where: WHERE条件字典

        Returns:
            查询结果字典，如果没有结果返回None
        """
        columns_str = ", ".join(columns) if columns else "*"

        if where:
            where_clause = " AND ".join([f"{col} = %s" for col in where.keys()])
            sql = f"""
                SELECT {columns_str}
                FROM {table}
                WHERE {where_clause}
                LIMIT 1
            """
            params = tuple(where.values())
        else:
            sql = f"""
                SELECT {columns_str}
                FROM {table}
                LIMIT 1
            """
            params = None

        return self.execute_query(sql, params, fetch_one=True)

    def select_many(
        self,
        table: str,
        columns: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None,
        order_by: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        查询多条记录

        Args:
            table: 表名
            columns: 查询的列名列表，None表示查询所有列
            where: WHERE条件字典
            order_by: 排序字段（如 "created_at DESC"）
            limit: 限制返回记录数
            offset: 偏移量

        Returns:
            查询结果列表
        """
        columns_str = ", ".join(columns) if columns else "*"

        sql = f"SELECT {columns_str} FROM {table}"
        params = []

        if where:
            where_clause = " AND ".join([f"{col} = %s" for col in where.keys()])
            sql += f" WHERE {where_clause}"
            params.extend(where.values())

        if order_by:
            # 验证order_by参数，防止SQL注入
            # 只允许字母、数字、下划线、点号、逗号、空格和ASC/DESC关键字
            import re
            # 移除多余空格并规范化
            order_by_normalized = ' '.join(order_by.split())
            # 验证格式：column_name [ASC|DESC][, column_name [ASC|DESC]]*
            if not re.match(r'^[a-zA-Z0-9_.]+(\s+(ASC|DESC))?(\s*,\s*[a-zA-Z0-9_.]+(\s+(ASC|DESC))?)*$', order_by_normalized, re.IGNORECASE):
                raise ValueError(f"Invalid order_by parameter: {order_by}")
            sql += f" ORDER BY {order_by_normalized}"

        if limit:
            # 验证limit参数是整数
            if not isinstance(limit, int) or limit < 0:
                raise ValueError(f"Invalid limit parameter: {limit}")
            sql += f" LIMIT {limit}"

        if offset:
            # 验证offset参数是整数
            if not isinstance(offset, int) or offset < 0:
                raise ValueError(f"Invalid offset parameter: {offset}")
            sql += f" OFFSET {offset}"

        return self.execute_query(sql, tuple(params) if params else None)

    def count(
        self,
        table: str,
        where: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        统计记录数

        Args:
            table: 表名
            where: WHERE条件字典

        Returns:
            记录数
        """
        sql = f"SELECT COUNT(*) as count FROM {table}"
        params = None

        if where:
            where_clause = " AND ".join([f"{col} = %s" for col in where.keys()])
            sql += f" WHERE {where_clause}"
            params = tuple(where.values())

        result = self.execute_query(sql, params, fetch_one=True)
        return result["count"] if result else 0

    def exists(
        self,
        table: str,
        where: Dict[str, Any],
    ) -> bool:
        """
        检查记录是否存在

        Args:
            table: 表名
            where: WHERE条件字典

        Returns:
            记录是否存在
        """
        return self.count(table, where) > 0

    def _extract_table_name(self, sql: str) -> str:
        """
        从SQL语句中提取表名

        Args:
            sql: SQL语句

        Returns:
            表名
        """
        sql_upper = sql.upper().strip()

        try:
            if "FROM" in sql_upper:
                parts = sql_upper.split("FROM")[1].strip().split()
                return parts[0].lower()
            elif "INTO" in sql_upper:
                parts = sql_upper.split("INTO")[1].strip().split()
                return parts[0].lower()
            elif "UPDATE" in sql_upper:
                parts = sql_upper.split("UPDATE")[1].strip().split()
                return parts[0].lower()
            else:
                return "unknown"
        except Exception:
            return "unknown"

    def _extract_operation(self, sql: str) -> str:
        """
        从SQL语句中提取操作类型

        Args:
            sql: SQL语句

        Returns:
            操作类型（SELECT/INSERT/UPDATE/DELETE）
        """
        sql_upper = sql.upper().strip()

        if sql_upper.startswith("SELECT"):
            return "SELECT"
        elif sql_upper.startswith("INSERT"):
            return "INSERT"
        elif sql_upper.startswith("UPDATE"):
            return "UPDATE"
        elif sql_upper.startswith("DELETE"):
            return "DELETE"
        else:
            return "UNKNOWN"

    def close(self):
        """关闭数据库管理器"""
        if self.pool:
            self.pool.close()
            logger.info("DatabaseManager closed")

    def test_connection(self) -> bool:
        """
        测试数据库连接是否正常

        Returns:
            连接是否正常
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                cursor.close()
                return result is not None
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False

    def get_pool_status(self) -> Dict[str, Any]:
        """
        获取连接池状态

        Returns:
            连接池状态字典
        """
        return self.pool.get_pool_status()

    def __repr__(self) -> str:
        return f"DatabaseManager(pool={self.pool})"


# 全局数据库管理器实例
_database_manager: Optional[DatabaseManager] = None


def get_database_manager() -> DatabaseManager:
    """
    获取全局数据库管理器实例（单例模式）

    Returns:
        DatabaseManager实例
    """
    global _database_manager

    if _database_manager is None:
        _database_manager = DatabaseManager()

    return _database_manager
