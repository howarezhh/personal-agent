"""
消息仓储模块
提供消息数据的CRUD操作
"""

from typing import Optional, List
from datetime import datetime
import json
from backend.database.repositories.user_repository import BaseRepository
from backend.database.database_manager import DatabaseManager, get_database_manager
from backend.models.message import Message, MessageCreate, MessageUpdate, MessageType
from backend.utils.logger import get_logger


logger = get_logger(__name__)


class MessageRepository(BaseRepository):
    """
    消息仓储类

    功能：
    1. 消息CRUD操作
    2. 会话消息查询
    3. 消息历史管理
    """

    TABLE_NAME = "messages"

    def create_message(self, message_create: MessageCreate) -> Message:
        """
        创建消息

        Args:
            message_create: 消息创建数据

        Returns:
            创建的消息对象

        Raises:
            ValueError: 数据验证失败
            Exception: 数据库操作失败
        """
        # 验证数据
        is_valid, error_msg = message_create.validate()
        if not is_valid:
            raise ValueError(error_msg)

        # 创建消息对象
        message = message_create.to_message()
        message.created_at = datetime.utcnow()

        # 插入数据库
        data = {
            "message_id": message.message_id,
            "conversation_id": message.conversation_id,
            "message_type": message.message_type,
            "content": message.content,
            "sequence_number": message.sequence_number,
            "parent_message_id": message.parent_message_id,
            "created_at": message.created_at,
            "metadata": json.dumps(message.metadata, ensure_ascii=False) if message.metadata else None,
        }

        self.db.insert_one(self.TABLE_NAME, data, return_id=False)

        logger.info(
            f"Message created: message_id={message.message_id}, "
            f"conversation_id={message.conversation_id}, type={message.message_type}"
        )
        return message

    def get_message_by_id(self, message_id: str) -> Optional[Message]:
        """
        根据消息ID获取消息

        Args:
            message_id: 消息ID

        Returns:
            消息对象，如果不存在返回None
        """
        result = self.db.select_one(
            table=self.TABLE_NAME,
            where={"message_id": message_id}
        )
        return self._dict_to_model(result, Message)

    def get_conversation_messages(
        self,
        conversation_id: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        order: str = "ASC",
    ) -> List[Message]:
        """
        获取会话的所有消息

        Args:
            conversation_id: 会话ID
            limit: 限制返回数量
            offset: 偏移量
            order: 排序方式（ASC/DESC）

        Returns:
            消息列表
        """
        results = self.db.select_many(
            table=self.TABLE_NAME,
            where={"conversation_id": conversation_id},
            order_by=f"sequence_number {order}",
            limit=limit,
            offset=offset,
        )

        return self._dicts_to_models(results, Message)

    def get_conversation_history(
        self,
        conversation_id: str,
        limit: Optional[int] = None,
        include_system: bool = False,
    ) -> List[Message]:
        """
        获取会话历史（用于LLM上下文）

        Args:
            conversation_id: 会话ID
            limit: 限制返回数量（最近的N条消息）
            include_system: 是否包含系统消息

        Returns:
            消息列表（按时间正序）
        """
        if include_system:
            where_clause = "conversation_id = %s"
            params = [conversation_id]
        else:
            where_clause = "conversation_id = %s AND message_type != %s"
            params = [conversation_id, "system"]

        sql = f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE {where_clause}
            ORDER BY sequence_number DESC
        """

        if limit:
            sql += f" LIMIT {limit}"

        results = self.db.execute_query(sql, tuple(params))

        # 将元组转换为列表，然后反转，使其按时间正序
        results_list = list(results)
        results_list.reverse()

        return self._dicts_to_models(results_list, Message)

    def get_last_message(
        self,
        conversation_id: str,
        message_type: Optional[MessageType] = None
    ) -> Optional[Message]:
        """
        获取会话的最后一条消息

        Args:
            conversation_id: 会话ID
            message_type: 消息类型过滤

        Returns:
            消息对象，如果不存在返回None
        """
        where = {"conversation_id": conversation_id}
        if message_type:
            where["message_type"] = message_type

        sql = f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE conversation_id = %s
        """
        params = [conversation_id]

        if message_type:
            sql += " AND message_type = %s"
            params.append(message_type)

        sql += " ORDER BY sequence_number DESC LIMIT 1"

        result = self.db.execute_query(sql, tuple(params), fetch_one=True)
        return self._dict_to_model(result, Message)

    def get_next_sequence_number(self, conversation_id: str) -> int:
        """
        获取会话的下一个序号

        Args:
            conversation_id: 会话ID

        Returns:
            下一个序号
        """
        sql = f"""
            SELECT COALESCE(MAX(sequence_number), 0) + 1 as next_seq
            FROM {self.TABLE_NAME}
            WHERE conversation_id = %s
        """

        result = self.db.execute_query(sql, (conversation_id,), fetch_one=True)
        return result["next_seq"] if result else 1

    def update_message(
        self,
        message_id: str,
        message_update: MessageUpdate
    ) -> bool:
        """
        更新消息

        Args:
            message_id: 消息ID
            message_update: 消息更新数据

        Returns:
            是否更新成功

        Raises:
            ValueError: 消息不存在
            Exception: 数据库操作失败
        """
        # 检查消息是否存在
        if not self.exists_by_id(message_id):
            raise ValueError(f"消息不存在: message_id={message_id}")

        # 构建更新数据
        update_data = message_update.to_dict()
        if not update_data:
            return False

        # 执行更新
        affected_rows = self.db.update_one(
            table=self.TABLE_NAME,
            data=update_data,
            where={"message_id": message_id}
        )

        logger.info(
            f"Message updated: message_id={message_id}, "
            f"fields={list(update_data.keys())}"
        )
        return affected_rows > 0

    def delete_message(self, message_id: str) -> bool:
        """
        删除消息

        Args:
            message_id: 消息ID

        Returns:
            是否删除成功

        Raises:
            ValueError: 消息不存在
            Exception: 数据库操作失败
        """
        # 检查消息是否存在
        if not self.exists_by_id(message_id):
            raise ValueError(f"消息不存在: message_id={message_id}")

        # 物理删除记录
        affected_rows = self.db.delete_one(
            table=self.TABLE_NAME,
            where={"message_id": message_id}
        )

        logger.info(f"Message deleted: message_id={message_id}")
        return affected_rows > 0

    def delete_conversation_messages(self, conversation_id: str) -> int:
        """
        删除会话的所有消息

        Args:
            conversation_id: 会话ID

        Returns:
            删除的消息数量
        """
        affected_rows = self.db.delete_one(
            table=self.TABLE_NAME,
            where={"conversation_id": conversation_id}
        )

        logger.info(
            f"Conversation messages deleted: conversation_id={conversation_id}, "
            f"count={affected_rows}"
        )
        return affected_rows

    def exists_by_id(self, message_id: str) -> bool:
        """
        检查消息ID是否存在

        Args:
            message_id: 消息ID

        Returns:
            是否存在
        """
        return self.db.exists(self.TABLE_NAME, {"message_id": message_id})

    def count_conversation_messages(
        self,
        conversation_id: str,
        message_type: Optional[MessageType] = None
    ) -> int:
        """
        统计会话的消息数量

        Args:
            conversation_id: 会话ID
            message_type: 消息类型过滤

        Returns:
            消息数量
        """
        where = {"conversation_id": conversation_id}
        if message_type:
            where["message_type"] = message_type

        return self.db.count(self.TABLE_NAME, where)

    def search_messages(
        self,
        conversation_id: str,
        keyword: str,
        limit: Optional[int] = None,
    ) -> List[Message]:
        """
        搜索会话中的消息

        Args:
            conversation_id: 会话ID
            keyword: 搜索关键词
            limit: 限制返回数量

        Returns:
            消息列表
        """
        sql = f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE conversation_id = %s AND content LIKE %s
            ORDER BY sequence_number DESC
        """

        if limit:
            sql += f" LIMIT {limit}"

        keyword_pattern = f"%{keyword}%"
        results = self.db.execute_query(sql, (conversation_id, keyword_pattern))

        return self._dicts_to_models(results, Message)

    def get_messages_by_type(
        self,
        conversation_id: str,
        message_type: MessageType,
        limit: Optional[int] = None,
    ) -> List[Message]:
        """
        根据类型获取消息

        Args:
            conversation_id: 会话ID
            message_type: 消息类型
            limit: 限制返回数量

        Returns:
            消息列表
        """
        results = self.db.select_many(
            table=self.TABLE_NAME,
            where={"conversation_id": conversation_id, "message_type": message_type},
            order_by="sequence_number DESC",
            limit=limit,
        )

        return self._dicts_to_models(results, Message)


# 全局消息仓储实例
_message_repository: Optional[MessageRepository] = None


def get_message_repository() -> MessageRepository:
    """
    获取全局消息仓储实例（单例模式）

    Returns:
        MessageRepository实例
    """
    global _message_repository

    if _message_repository is None:
        _message_repository = MessageRepository()

    return _message_repository
