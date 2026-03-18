"""
工具调用仓储模块
提供工具调用数据的CRUD操作
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
import json
from backend.database.repositories.user_repository import BaseRepository
from backend.models.tool_call import ToolCall, ToolCallCreate, ToolCallUpdate, ToolCallStatus
from backend.utils.logger import get_logger
from backend.utils.time_utils import utc_now


logger = get_logger(__name__)


class ToolCallRepository(BaseRepository):
    _table_schema_cache: Optional[Dict[str, str]] = None

    def _get_table_schema(self) -> Dict[str, str]:
        if self._table_schema_cache is None:
            rows = self.db.execute_query(f"SHOW COLUMNS FROM {self.TABLE_NAME}") or []
            self._table_schema_cache = {
                row.get("Field"): row.get("Type", "")
                for row in rows
                if isinstance(row, dict) and row.get("Field")
            }
        return self._table_schema_cache

    def _filter_supported_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        schema = self._get_table_schema()
        filtered = {key: value for key, value in data.items() if key in schema}
        unsupported_fields = sorted(set(data.keys()) - set(filtered.keys()))
        if unsupported_fields:
            logger.warning("Tool call table missing columns, dropping fields: %s", unsupported_fields)
        return filtered

    def _normalize_status(self, status: Optional[str]) -> Optional[str]:
        if status is None:
            return None
        status_type = str(self._get_table_schema().get("status", ""))
        if status == "timeout" and "timeout" not in status_type:
            logger.warning("Tool call table status enum missing 'timeout', fallback to 'failed'")
            return "failed"
        return status

    """
    工具调用仓储类

    功能：
    1. 工具调用CRUD操作
    2. 按execution_id查询
    3. 按工具名称查询
    4. 按状态查询
    5. 工具调用统计
    """

    TABLE_NAME = "tool_calls"

    def create_tool_call(self, tool_call_create: ToolCallCreate) -> ToolCall:
        """
        创建工具调用记录

        Args:
            tool_call_create: 工具调用创建数据

        Returns:
            创建的工具调用对象

        Raises:
            ValueError: 数据验证失败
            Exception: 数据库操作失败
        """
        # 验证数据
        is_valid, error_msg = tool_call_create.validate()
        if not is_valid:
            raise ValueError(error_msg)

        # 创建工具调用对象
        tool_call = tool_call_create.to_tool_call()

        # 插入数据库
        data = {
            "call_id": tool_call.call_id,
            "execution_id": tool_call.execution_id,
            "tool_name": tool_call.tool_name,
            "tool_type": tool_call.tool_type,
            "tool_input": json.dumps(tool_call.tool_input, ensure_ascii=False) if tool_call.tool_input else None,
            "tool_output": json.dumps(tool_call.tool_output, ensure_ascii=False) if tool_call.tool_output else None,
            "status": tool_call.status,
            "error_message": tool_call.error_message,
            "execution_time_ms": tool_call.execution_time_ms,
            "created_at": tool_call.created_at,
            "completed_at": tool_call.completed_at,
            "metadata": json.dumps(tool_call.metadata, ensure_ascii=False) if tool_call.metadata else None,
        }

        data["status"] = self._normalize_status(data.get("status"))
        self.db.insert_one(self.TABLE_NAME, self._filter_supported_data(data), return_id=False)

        logger.info(
            f"Tool call created: call_id={tool_call.call_id}, "
            f"tool_name={tool_call.tool_name}, execution_id={tool_call.execution_id}"
        )
        return tool_call

    def get_tool_call_by_id(self, call_id: str) -> Optional[ToolCall]:
        """
        根据调用ID获取工具调用记录

        Args:
            call_id: 调用ID

        Returns:
            工具调用对象，如果不存在返回None
        """
        result = self.db.select_one(
            table=self.TABLE_NAME,
            where={"call_id": call_id}
        )
        return self._dict_to_model(result, ToolCall)

    def get_tool_calls_by_execution_id(
        self,
        execution_id: str,
        limit: Optional[int] = None
    ) -> List[ToolCall]:
        """
        根据执行ID获取所有工具调用记录

        Args:
            execution_id: 执行ID
            limit: 限制返回数量

        Returns:
            工具调用列表
        """
        results = self.db.select_many(
            table=self.TABLE_NAME,
            where={"execution_id": execution_id},
            order_by="created_at ASC",
            limit=limit,
        )

        return self._dicts_to_models(results, ToolCall)

    def get_tool_calls_by_tool_name(
        self,
        tool_name: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[ToolCall]:
        """
        根据工具名称获取工具调用记录

        Args:
            tool_name: 工具名称
            limit: 限制返回数量
            offset: 偏移量

        Returns:
            工具调用列表
        """
        results = self.db.select_many(
            table=self.TABLE_NAME,
            where={"tool_name": tool_name},
            order_by="created_at DESC",
            limit=limit,
            offset=offset,
        )

        return self._dicts_to_models(results, ToolCall)

    def get_tool_calls_by_status(
        self,
        status: ToolCallStatus,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[ToolCall]:
        """
        根据状态获取工具调用记录

        Args:
            status: 工具调用状态
            limit: 限制返回数量
            offset: 偏移量

        Returns:
            工具调用列表
        """
        results = self.db.select_many(
            table=self.TABLE_NAME,
            where={"status": status},
            order_by="created_at DESC",
            limit=limit,
            offset=offset,
        )

        return self._dicts_to_models(results, ToolCall)

    def update_tool_call(
        self,
        call_id: str,
        tool_call_update: ToolCallUpdate
    ) -> bool:
        """
        更新工具调用记录

        Args:
            call_id: 调用ID
            tool_call_update: 工具调用更新数据

        Returns:
            是否更新成功

        Raises:
            ValueError: 工具调用不存在
            Exception: 数据库操作失败
        """
        # 检查工具调用是否存在
        if not self.exists_by_id(call_id):
            raise ValueError(f"工具调用不存在: call_id={call_id}")

        # 构建更新数据
        update_data = tool_call_update.to_dict()
        if not update_data:
            return False

        # 执行更新
        update_data["status"] = self._normalize_status(update_data.get("status"))
        update_data = self._filter_supported_data(update_data)
        if not update_data:
            return False

        affected_rows = self.db.update_one(
            table=self.TABLE_NAME,
            data=update_data,
            where={"call_id": call_id}
        )

        logger.info(
            f"Tool call updated: call_id={call_id}, "
            f"fields={list(update_data.keys())}"
        )
        return affected_rows > 0

    def mark_tool_call_success(
        self,
        call_id: str,
        tool_output: Dict[str, Any],
        execution_time_ms: int
    ) -> bool:
        """
        标记工具调用成功

        Args:
            call_id: 调用ID
            tool_output: 工具输出
            execution_time_ms: 执行时间（毫秒）

        Returns:
            是否更新成功
        """
        update = ToolCallUpdate(
            tool_output=tool_output,
            status="success",
            execution_time_ms=execution_time_ms,
            completed_at=utc_now()
        )
        return self.update_tool_call(call_id, update)

    def mark_tool_call_failed(
        self,
        call_id: str,
        error_message: str,
        execution_time_ms: Optional[int] = None
    ) -> bool:
        """
        标记工具调用失败

        Args:
            call_id: 调用ID
            error_message: 错误信息
            execution_time_ms: 执行时间（毫秒）

        Returns:
            是否更新成功
        """
        update = ToolCallUpdate(
            status="failed",
            error_message=error_message,
            execution_time_ms=execution_time_ms,
            completed_at=utc_now()
        )
        return self.update_tool_call(call_id, update)

    def mark_tool_call_timeout(
        self,
        call_id: str,
        execution_time_ms: int
    ) -> bool:
        """
        标记工具调用超时

        Args:
            call_id: 调用ID
            execution_time_ms: 执行时间（毫秒）

        Returns:
            是否更新成功
        """
        update = ToolCallUpdate(
            status="timeout",
            error_message="Tool call timeout",
            execution_time_ms=execution_time_ms,
            completed_at=utc_now()
        )
        return self.update_tool_call(call_id, update)

    def delete_tool_call(self, call_id: str) -> bool:
        """
        删除工具调用记录

        Args:
            call_id: 调用ID

        Returns:
            是否删除成功

        Raises:
            ValueError: 工具调用不存在
            Exception: 数据库操作失败
        """
        # 检查工具调用是否存在
        if not self.exists_by_id(call_id):
            raise ValueError(f"工具调用不存在: call_id={call_id}")

        affected_rows = self.db.delete_one(
            table=self.TABLE_NAME,
            where={"call_id": call_id}
        )

        logger.info(f"Tool call deleted: call_id={call_id}")
        return affected_rows > 0

    def delete_tool_calls_by_execution_id(self, execution_id: str) -> int:
        """
        删除指定执行ID的所有工具调用记录

        Args:
            execution_id: 执行ID

        Returns:
            删除的记录数量
        """
        affected_rows = self.db.delete_one(
            table=self.TABLE_NAME,
            where={"execution_id": execution_id}
        )

        logger.info(f"Deleted {affected_rows} tool calls for execution_id={execution_id}")
        return affected_rows

    def count_tool_calls_by_execution_id(self, execution_id: str) -> int:
        """
        统计指定执行ID的工具调用数量

        Args:
            execution_id: 执行ID

        Returns:
            工具调用数量
        """
        return self.db.count(self.TABLE_NAME, {"execution_id": execution_id})

    def count_tool_calls_by_tool_name(self, tool_name: str) -> int:
        """
        统计指定工具的调用次数

        Args:
            tool_name: 工具名称

        Returns:
            调用次数
        """
        return self.db.count(self.TABLE_NAME, {"tool_name": tool_name})

    def count_tool_calls_by_status(self, status: ToolCallStatus) -> int:
        """
        统计指定状态的工具调用数量

        Args:
            status: 工具调用状态

        Returns:
            工具调用数量
        """
        return self.db.count(self.TABLE_NAME, {"status": status})

    def get_tool_call_statistics(
        self,
        tool_name: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        获取工具调用统计信息

        Args:
            tool_name: 工具名称（可选，不传则统计所有工具）
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）

        Returns:
            统计信息字典，包含：
            - total_calls: 总调用次数
            - success_calls: 成功次数
            - failed_calls: 失败次数
            - timeout_calls: 超时次数
            - avg_execution_time_ms: 平均执行时间（毫秒）
            - success_rate: 成功率
        """
        # 构建查询条件
        where_clause = "1=1"
        params = []

        if tool_name:
            where_clause += " AND tool_name = %s"
            params.append(tool_name)

        if start_date:
            where_clause += " AND created_at >= %s"
            params.append(start_date)

        if end_date:
            where_clause += " AND created_at <= %s"
            params.append(end_date)

        sql = f"""
            SELECT
                COUNT(*) as total_calls,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_calls,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_calls,
                SUM(CASE WHEN status = 'timeout' THEN 1 ELSE 0 END) as timeout_calls,
                AVG(CASE WHEN execution_time_ms IS NOT NULL THEN execution_time_ms ELSE NULL END) as avg_execution_time_ms
            FROM {self.TABLE_NAME}
            WHERE {where_clause}
        """

        result = self.db.execute_query(sql, tuple(params))

        if result and len(result) > 0:
            stats = result[0]
            total_calls = stats.get("total_calls", 0)
            success_calls = stats.get("success_calls", 0)

            return {
                "total_calls": total_calls,
                "success_calls": success_calls,
                "failed_calls": stats.get("failed_calls", 0),
                "timeout_calls": stats.get("timeout_calls", 0),
                "avg_execution_time_ms": float(stats.get("avg_execution_time_ms", 0)) if stats.get("avg_execution_time_ms") else 0,
                "success_rate": (success_calls / total_calls * 100) if total_calls > 0 else 0,
            }

        return {
            "total_calls": 0,
            "success_calls": 0,
            "failed_calls": 0,
            "timeout_calls": 0,
            "avg_execution_time_ms": 0,
            "success_rate": 0,
        }

    def get_tool_usage_ranking(
        self,
        limit: int = 10,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        获取工具使用排名

        Args:
            limit: 返回前N个工具
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）

        Returns:
            工具使用排名列表，每项包含：
            - tool_name: 工具名称
            - call_count: 调用次数
            - success_count: 成功次数
            - success_rate: 成功率
        """
        # 构建查询条件
        where_clause = "1=1"
        params = []

        if start_date:
            where_clause += " AND created_at >= %s"
            params.append(start_date)

        if end_date:
            where_clause += " AND created_at <= %s"
            params.append(end_date)

        sql = f"""
            SELECT
                tool_name,
                COUNT(*) as call_count,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count
            FROM {self.TABLE_NAME}
            WHERE {where_clause}
            GROUP BY tool_name
            ORDER BY call_count DESC
            LIMIT {limit}
        """

        results = self.db.execute_query(sql, tuple(params))

        rankings = []
        for row in results:
            call_count = row.get("call_count", 0)
            success_count = row.get("success_count", 0)

            rankings.append({
                "tool_name": row.get("tool_name"),
                "call_count": call_count,
                "success_count": success_count,
                "success_rate": (success_count / call_count * 100) if call_count > 0 else 0,
            })

        return rankings

    def exists_by_id(self, call_id: str) -> bool:
        """
        检查调用ID是否存在

        Args:
            call_id: 调用ID

        Returns:
            是否存在
        """
        return self.db.exists(self.TABLE_NAME, {"call_id": call_id})


# 全局工具调用仓储实例
_tool_call_repository: Optional[ToolCallRepository] = None


def get_tool_call_repository() -> ToolCallRepository:
    """
    获取全局工具调用仓储实例（单例模式）

    Returns:
        ToolCallRepository实例
    """
    global _tool_call_repository

    if _tool_call_repository is None:
        _tool_call_repository = ToolCallRepository()

    return _tool_call_repository
