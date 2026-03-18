"""
智能体执行记录仓储模块
提供智能体执行记录的CRUD操作
"""

from typing import Optional, List
import json
from backend.database.repositories.user_repository import BaseRepository
from backend.models.agent_execution import (
    AgentExecution,
    AgentExecutionCreate,
    AgentExecutionUpdate,
    AgentType,
    ExecutionStatus,
)
from backend.utils.logger import get_logger
from backend.utils.time_utils import utc_now


logger = get_logger(__name__)


class AgentExecutionRepository(BaseRepository):
    """
    智能体执行记录仓储类

    功能：
    1. 执行记录CRUD操作
    2. 会话执行记录查询
    3. 智能体执行统计
    """

    TABLE_NAME = "agent_executions"

    def create_execution(self, execution_create: AgentExecutionCreate) -> AgentExecution:
        """
        创建智能体执行记录

        Args:
            execution_create: 执行记录创建数据

        Returns:
            创建的执行记录对象

        Raises:
            Exception: 数据库操作失败
        """
        # 创建执行记录对象
        execution = execution_create.to_agent_execution()

        # 插入数据库
        data = {
            "execution_id": execution.execution_id,
            "conversation_id": execution.conversation_id,
            "message_id": execution.message_id,
            "agent_name": execution.agent_name,
            "agent_type": execution.agent_type,
            "input_data": json.dumps(execution.input_data, ensure_ascii=False) if execution.input_data else None,
            "output_data": json.dumps(execution.output_data, ensure_ascii=False) if execution.output_data else None,
            "status": execution.status,
            "error_message": execution.error_message,
            "execution_time_ms": execution.execution_time_ms,
            "created_at": execution.created_at,
            "completed_at": execution.completed_at,
            "metadata": json.dumps(execution.metadata, ensure_ascii=False) if execution.metadata else None,
        }

        self.db.insert_one(self.TABLE_NAME, data, return_id=False)

        logger.info(
            f"Agent execution created: execution_id={execution.execution_id}, "
            f"agent_name={execution.agent_name}, agent_type={execution.agent_type}"
        )
        return execution

    def create_execution_with_result(
        self,
        agent_name: str,
        agent_type: str,
        input_data: dict,
        output_data: dict,
        status: str,
        execution_time_ms: int,
        conversation_id: Optional[str] = None,
        message_id: Optional[str] = None,
        error_message: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> AgentExecution:
        """
        一次性创建完整的执行记录（优化版本，避免创建后再更新）

        Args:
            agent_name: 智能体名称
            agent_type: 智能体类型
            input_data: 输入数据
            output_data: 输出数据
            status: 执行状态
            execution_time_ms: 执行时间（毫秒）
            conversation_id: 会话ID（可选，直接工具调用时为None）
            message_id: 消息ID（可选）
            error_message: 错误信息（可选）
            metadata: 元数据（可选）

        Returns:
            创建的执行记录对象

        Raises:
            Exception: 数据库操作失败
        """
        from backend.models.agent_execution import AgentExecution
        import uuid

        # 创建完整的执行记录对象
        execution = AgentExecution(
            execution_id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            message_id=message_id,
            agent_name=agent_name,
            agent_type=agent_type,
            input_data=input_data,
            output_data=output_data,
            status=status,
            error_message=error_message,
            execution_time_ms=execution_time_ms,
            created_at=utc_now(),
            completed_at=utc_now(),
            metadata=metadata or {}
        )

        # 插入数据库
        data = {
            "execution_id": execution.execution_id,
            "conversation_id": execution.conversation_id,
            "message_id": execution.message_id,
            "agent_name": execution.agent_name,
            "agent_type": execution.agent_type,
            "input_data": json.dumps(execution.input_data, ensure_ascii=False) if execution.input_data else None,
            "output_data": json.dumps(execution.output_data, ensure_ascii=False) if execution.output_data else None,
            "status": execution.status,
            "error_message": execution.error_message,
            "execution_time_ms": execution.execution_time_ms,
            "created_at": execution.created_at,
            "completed_at": execution.completed_at,
            "metadata": json.dumps(execution.metadata, ensure_ascii=False) if execution.metadata else None,
        }

        self.db.insert_one(self.TABLE_NAME, data, return_id=False)

        logger.info(
            f"Agent execution created with result: execution_id={execution.execution_id}, "
            f"agent_name={execution.agent_name}, status={execution.status}, "
            f"execution_time_ms={execution_time_ms}"
        )
        return execution

    def get_execution_by_id(self, execution_id: str) -> Optional[AgentExecution]:
        """
        根据执行ID获取执行记录

        Args:
            execution_id: 执行ID

        Returns:
            执行记录对象，如果不存在返回None
        """
        result = self.db.select_one(
            table=self.TABLE_NAME,
            where={"execution_id": execution_id}
        )
        return self._dict_to_model(result, AgentExecution)

    def get_conversation_executions(
        self,
        conversation_id: Optional[str],
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        agent_type: Optional[AgentType] = None,
    ) -> List[AgentExecution]:
        """
        获取会话的所有执行记录

        Args:
            conversation_id: 会话ID（如果为None，返回所有直接工具调用的记录）
            limit: 限制返回数量
            offset: 偏移量
            agent_type: 智能体类型过滤

        Returns:
            执行记录列表
        """
        where = {}
        if conversation_id is not None:
            where["conversation_id"] = conversation_id
        else:
            # 查询直接工具调用（conversation_id为NULL）
            # 需要使用原始SQL
            pass

        if agent_type:
            where["agent_type"] = agent_type

        results = self.db.select_many(
            table=self.TABLE_NAME,
            where=where,
            order_by="created_at DESC",
            limit=limit,
            offset=offset,
        )

        return self._dicts_to_models(results, AgentExecution)

    def get_message_executions(
        self,
        message_id: str,
        limit: Optional[int] = None,
    ) -> List[AgentExecution]:
        """
        获取消息相关的所有执行记录

        Args:
            message_id: 消息ID
            limit: 限制返回数量

        Returns:
            执行记录列表
        """
        results = self.db.select_many(
            table=self.TABLE_NAME,
            where={"message_id": message_id},
            order_by="created_at ASC",
            limit=limit,
        )

        return self._dicts_to_models(results, AgentExecution)

    def update_execution(
        self,
        execution_id: str,
        execution_update: AgentExecutionUpdate
    ) -> bool:
        """
        更新执行记录

        Args:
            execution_id: 执行ID
            execution_update: 执行记录更新数据

        Returns:
            是否更新成功

        Raises:
            ValueError: 执行记录不存在
            Exception: 数据库操作失败
        """
        # 检查执行记录是否存在
        if not self.exists_by_id(execution_id):
            raise ValueError(f"执行记录不存在: execution_id={execution_id}")

        # 构建更新数据
        update_data = execution_update.to_dict()
        if not update_data:
            return False

        # 执行更新
        affected_rows = self.db.update_one(
            table=self.TABLE_NAME,
            data=update_data,
            where={"execution_id": execution_id}
        )

        logger.info(
            f"Agent execution updated: execution_id={execution_id}, "
            f"fields={list(update_data.keys())}"
        )
        return affected_rows > 0

    def mark_execution_success(
        self,
        execution_id: str,
        output_data: dict,
        execution_time_ms: int
    ) -> bool:
        """
        标记执行成功

        Args:
            execution_id: 执行ID
            output_data: 输出数据
            execution_time_ms: 执行时间（毫秒）

        Returns:
            是否更新成功
        """
        update = AgentExecutionUpdate(
            status="success",
            output_data=output_data,
            execution_time_ms=execution_time_ms,
            completed_at=utc_now(),
        )
        return self.update_execution(execution_id, update)

    def mark_execution_failed(
        self,
        execution_id: str,
        error_message: str,
        execution_time_ms: Optional[int] = None
    ) -> bool:
        """
        标记执行失败

        Args:
            execution_id: 执行ID
            error_message: 错误信息
            execution_time_ms: 执行时间（毫秒）

        Returns:
            是否更新成功
        """
        update = AgentExecutionUpdate(
            status="failed",
            error_message=error_message,
            execution_time_ms=execution_time_ms,
            completed_at=utc_now(),
        )
        return self.update_execution(execution_id, update)

    def delete_execution(self, execution_id: str) -> bool:
        """
        删除执行记录

        Args:
            execution_id: 执行ID

        Returns:
            是否删除成功

        Raises:
            ValueError: 执行记录不存在
            Exception: 数据库操作失败
        """
        # 检查执行记录是否存在
        if not self.exists_by_id(execution_id):
            raise ValueError(f"执行记录不存在: execution_id={execution_id}")

        # 物理删除记录
        affected_rows = self.db.delete_one(
            table=self.TABLE_NAME,
            where={"execution_id": execution_id}
        )

        logger.info(f"Agent execution deleted: execution_id={execution_id}")
        return affected_rows > 0

    def delete_conversation_executions(self, conversation_id: Optional[str]) -> int:
        """
        删除会话的所有执行记录

        Args:
            conversation_id: 会话ID（如果为None，删除所有直接工具调用的记录）

        Returns:
            删除的执行记录数量
        """
        if conversation_id is None:
            return 0  # 不允许批量删除直接工具调用记录

        affected_rows = self.db.delete_one(
            table=self.TABLE_NAME,
            where={"conversation_id": conversation_id}
        )

        logger.info(
            f"Conversation executions deleted: conversation_id={conversation_id}, "
            f"count={affected_rows}"
        )
        return affected_rows

    def exists_by_id(self, execution_id: str) -> bool:
        """
        检查执行ID是否存在

        Args:
            execution_id: 执行ID

        Returns:
            是否存在
        """
        return self.db.exists(self.TABLE_NAME, {"execution_id": execution_id})

    def count_conversation_executions(
        self,
        conversation_id: Optional[str],
        agent_type: Optional[AgentType] = None,
        status: Optional[ExecutionStatus] = None,
    ) -> int:
        """
        统计会话的执行记录数量

        Args:
            conversation_id: 会话ID（如果为None，统计所有直接工具调用的记录）
            agent_type: 智能体类型过滤
            status: 执行状态过滤

        Returns:
            执行记录数量
        """
        where = {}
        if conversation_id is not None:
            where["conversation_id"] = conversation_id

        if agent_type:
            where["agent_type"] = agent_type
        if status:
            where["status"] = status

        return self.db.count(self.TABLE_NAME, where)

    def get_executions_by_agent_type(
        self,
        conversation_id: Optional[str],
        agent_type: AgentType,
        limit: Optional[int] = None,
    ) -> List[AgentExecution]:
        """
        根据智能体类型获取执行记录

        Args:
            conversation_id: 会话ID（如果为None，查询所有直接工具调用的记录）
            agent_type: 智能体类型
            limit: 限制返回数量

        Returns:
            执行记录列表
        """
        where = {"agent_type": agent_type}
        if conversation_id is not None:
            where["conversation_id"] = conversation_id

        results = self.db.select_many(
            table=self.TABLE_NAME,
            where=where,
            order_by="created_at DESC",
            limit=limit,
        )

        return self._dicts_to_models(results, AgentExecution)

    def get_executions_by_status(
        self,
        conversation_id: Optional[str],
        status: ExecutionStatus,
        limit: Optional[int] = None,
    ) -> List[AgentExecution]:
        """
        根据执行状态获取执行记录

        Args:
            conversation_id: 会话ID（如果为None，查询所有直接工具调用的记录）
            status: 执行状态
            limit: 限制返回数量

        Returns:
            执行记录列表
        """
        where = {"status": status}
        if conversation_id is not None:
            where["conversation_id"] = conversation_id

        results = self.db.select_many(
            table=self.TABLE_NAME,
            where=where,
            order_by="created_at DESC",
            limit=limit,
        )

        return self._dicts_to_models(results, AgentExecution)

    def get_failed_executions(
        self,
        conversation_id: Optional[str],
        limit: Optional[int] = None,
    ) -> List[AgentExecution]:
        """
        获取失败的执行记录

        Args:
            conversation_id: 会话ID（如果为None，查询所有直接工具调用的记录）
            limit: 限制返回数量

        Returns:
            执行记录列表
        """
        return self.get_executions_by_status(conversation_id, "failed", limit)

    def get_execution_statistics(self, conversation_id: Optional[str]) -> dict:
        """
        获取会话的执行统计信息

        Args:
            conversation_id: 会话ID（如果为None，统计所有直接工具调用的记录）

        Returns:
            统计信息字典
        """
        sql = f"""
            SELECT
                agent_type,
                status,
                COUNT(*) as count,
                AVG(execution_time_ms) as avg_time_ms,
                MAX(execution_time_ms) as max_time_ms,
                MIN(execution_time_ms) as min_time_ms
            FROM {self.TABLE_NAME}
            WHERE conversation_id {'= %s' if conversation_id else 'IS NULL'}
            GROUP BY agent_type, status
        """

        params = (conversation_id,) if conversation_id else ()
        results = self.db.execute_query(sql, params)

        # 组织统计数据
        statistics = {
            "total_executions": 0,
            "by_agent_type": {},
            "by_status": {},
        }

        for row in results:
            agent_type = row["agent_type"]
            status = row["status"]
            count = row["count"]

            statistics["total_executions"] += count

            # 按智能体类型统计
            if agent_type not in statistics["by_agent_type"]:
                statistics["by_agent_type"][agent_type] = {
                    "total": 0,
                    "success": 0,
                    "failed": 0,
                    "avg_time_ms": 0,
                }

            statistics["by_agent_type"][agent_type]["total"] += count
            statistics["by_agent_type"][agent_type][status] = count
            statistics["by_agent_type"][agent_type]["avg_time_ms"] = row["avg_time_ms"]

            # 按状态统计
            if status not in statistics["by_status"]:
                statistics["by_status"][status] = 0
            statistics["by_status"][status] += count

        return statistics


# 全局智能体执行记录仓储实例
_agent_execution_repository: Optional[AgentExecutionRepository] = None


def get_agent_execution_repository() -> AgentExecutionRepository:
    """
    获取全局智能体执行记录仓储实例（单例模式）

    Returns:
        AgentExecutionRepository实例
    """
    global _agent_execution_repository

    if _agent_execution_repository is None:
        _agent_execution_repository = AgentExecutionRepository()

    return _agent_execution_repository
