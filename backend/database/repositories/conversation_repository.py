"""
会话仓储模块
提供会话数据的CRUD操作
"""

from typing import Optional, List
from datetime import datetime
import json
from backend.database.repositories.user_repository import BaseRepository
from backend.database.database_manager import DatabaseManager, get_database_manager
from backend.models.conversation import Conversation, ConversationCreate, ConversationUpdate, ConversationSummary
from backend.utils.logger import get_logger


logger = get_logger(__name__)


class ConversationRepository(BaseRepository):
    """
    会话仓储类

    功能：
    1. 会话CRUD操作
    2. 用户会话查询
    3. 会话统计
    """

    TABLE_NAME = "conversations"

    def create_conversation(self, conversation_create: ConversationCreate) -> Conversation:
        """
        创建会话

        Args:
            conversation_create: 会话创建数据

        Returns:
            创建的会话对象

        Raises:
            Exception: 数据库操作失败
        """
        # 创建会话对象
        conversation = conversation_create.to_conversation()
        conversation.created_at = datetime.utcnow()
        conversation.updated_at = datetime.utcnow()

        # 插入数据库
        data = {
            "conversation_id": conversation.conversation_id,
            "user_id": conversation.user_id,
            "title": conversation.title,
            "description": conversation.description,
            "is_active": conversation.is_active,
            "message_count": conversation.message_count,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "metadata": json.dumps(conversation.metadata, ensure_ascii=False) if conversation.metadata else None,
        }

        self.db.insert_one(self.TABLE_NAME, data, return_id=False)

        logger.info(
            f"Conversation created: conversation_id={conversation.conversation_id}, "
            f"user_id={conversation.user_id}, title={conversation.title}"
        )
        return conversation

    def get_conversation_by_id(self, conversation_id: str) -> Optional[Conversation]:
        """
        根据会话ID获取会话

        Args:
            conversation_id: 会话ID

        Returns:
            会话对象，如果不存在返回None
        """
        result = self.db.select_one(
            table=self.TABLE_NAME,
            where={"conversation_id": conversation_id}
        )
        return self._dict_to_model(result, Conversation)

    def get_user_conversations(
        self,
        user_id: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        only_active: bool = True,
    ) -> List[Conversation]:
        """
        获取用户的所有会话

        Args:
            user_id: 用户ID
            limit: 限制返回数量
            offset: 偏移量
            only_active: 是否只返回激活的会话

        Returns:
            会话列表
        """
        where = {"user_id": user_id}
        if only_active:
            where["is_active"] = True

        results = self.db.select_many(
            table=self.TABLE_NAME,
            where=where,
            order_by="updated_at DESC",
            limit=limit,
            offset=offset,
        )

        return self._dicts_to_models(results, Conversation)

    def get_user_conversation_summaries(
        self,
        user_id: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        only_active: bool = True,
    ) -> List[ConversationSummary]:
        """
        获取用户的会话摘要列表（用于侧边栏展示）

        Args:
            user_id: 用户ID
            limit: 限制返回数量
            offset: 偏移量
            only_active: 是否只返回激活的会话

        Returns:
            会话摘要列表
        """
        # 构建SQL查询，联表获取最后一条消息
        where_clause = "c.user_id = %s"
        params = [user_id]

        if only_active:
            where_clause += " AND c.is_active = %s"
            params.append(True)

        sql = f"""
            SELECT
                c.conversation_id,
                c.title,
                c.message_count,
                c.updated_at,
                m.content as last_message_preview
            FROM {self.TABLE_NAME} c
            LEFT JOIN (
                SELECT conversation_id, content,
                       ROW_NUMBER() OVER (PARTITION BY conversation_id ORDER BY sequence_number DESC) as rn
                FROM messages
                WHERE message_type = 'user'
            ) m ON c.conversation_id = m.conversation_id AND m.rn = 1
            WHERE {where_clause}
            ORDER BY c.updated_at DESC
        """

        if limit:
            sql += f" LIMIT {limit}"
        if offset:
            sql += f" OFFSET {offset}"

        results = self.db.execute_query(sql, tuple(params))

        # 转换为ConversationSummary对象
        summaries = []
        for row in results:
            # 截取消息预览（最多50个字符）
            preview = row.get("last_message_preview")
            if preview and len(preview) > 50:
                preview = preview[:50] + "..."

            summary = ConversationSummary(
                conversation_id=row["conversation_id"],
                title=row["title"],
                message_count=row["message_count"],
                updated_at=row["updated_at"],
                last_message_preview=preview,
            )
            summaries.append(summary)

        return summaries

    def update_conversation(
        self,
        conversation_id: str,
        conversation_update: ConversationUpdate
    ) -> bool:
        """
        更新会话信息

        Args:
            conversation_id: 会话ID
            conversation_update: 会话更新数据

        Returns:
            是否更新成功

        Raises:
            ValueError: 会话不存在
            Exception: 数据库操作失败
        """
        # 检查会话是否存在
        if not self.exists_by_id(conversation_id):
            raise ValueError(f"会话不存在: conversation_id={conversation_id}")

        # 构建更新数据
        update_data = conversation_update.to_dict()
        if not update_data:
            return False

        # 添加更新时间
        update_data["updated_at"] = datetime.utcnow()

        # 执行更新
        affected_rows = self.db.update_one(
            table=self.TABLE_NAME,
            data=update_data,
            where={"conversation_id": conversation_id}
        )

        logger.info(
            f"Conversation updated: conversation_id={conversation_id}, "
            f"fields={list(update_data.keys())}"
        )
        return affected_rows > 0

    def update_message_count(self, conversation_id: str, increment: int = 1) -> bool:
        """
        更新会话的消息计数

        Args:
            conversation_id: 会话ID
            increment: 增量（正数增加，负数减少）

        Returns:
            是否更新成功
        """
        sql = f"""
            UPDATE {self.TABLE_NAME}
            SET message_count = message_count + %s,
                updated_at = %s
            WHERE conversation_id = %s
        """

        affected_rows = self.db.execute_update(
            sql,
            (increment, datetime.utcnow(), conversation_id)
        )

        if affected_rows == 0:
            logger.warning(
                f"Conversation message_count update affected no rows: conversation_id={conversation_id}, increment={increment}"
            )

        return affected_rows > 0

    def update_conversation_timestamp(self, conversation_id: str) -> bool:
        """
        更新会话的最后活动时间

        Args:
            conversation_id: 会话ID

        Returns:
            是否更新成功
        """
        sql = f"""
            UPDATE {self.TABLE_NAME}
            SET updated_at = %s
            WHERE conversation_id = %s
        """

        affected_rows = self.db.execute_update(
            sql,
            (datetime.utcnow(), conversation_id)
        )

        if affected_rows == 0:
            logger.warning(
                f"Conversation timestamp update affected no rows: conversation_id={conversation_id}"
            )

        return affected_rows > 0

    def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        """
        更新会话标题

        Args:
            conversation_id: 会话ID
            title: 新标题

        Returns:
            是否更新成功
        """
        update = ConversationUpdate(title=title)
        return self.update_conversation(conversation_id, update)

    def delete_conversation(self, conversation_id: str, soft_delete: bool = True) -> bool:
        """
        删除会话

        Args:
            conversation_id: 会话ID
            soft_delete: 是否软删除（默认True）

        Returns:
            是否删除成功

        Raises:
            ValueError: 会话不存在
            Exception: 数据库操作失败
        """
        # 检查会话是否存在
        if not self.exists_by_id(conversation_id):
            raise ValueError(f"会话不存在: conversation_id={conversation_id}")

        if soft_delete:
            # 软删除：设置is_active=False
            affected_rows = self.db.update_one(
                table=self.TABLE_NAME,
                data={"is_active": False, "updated_at": datetime.utcnow()},
                where={"conversation_id": conversation_id}
            )
            logger.info(f"Conversation soft deleted: conversation_id={conversation_id}")
        else:
            # 硬删除：物理删除记录
            affected_rows = self.db.delete_one(
                table=self.TABLE_NAME,
                where={"conversation_id": conversation_id}
            )
            logger.info(f"Conversation hard deleted: conversation_id={conversation_id}")

        return affected_rows > 0

    def exists_by_id(self, conversation_id: str) -> bool:
        """
        检查会话ID是否存在

        Args:
            conversation_id: 会话ID

        Returns:
            是否存在
        """
        return self.db.exists(self.TABLE_NAME, {"conversation_id": conversation_id})

    def count_user_conversations(self, user_id: str, only_active: bool = True) -> int:
        """
        统计用户的会话数量

        Args:
            user_id: 用户ID
            only_active: 是否只统计激活的会话

        Returns:
            会话数量
        """
        where = {"user_id": user_id}
        if only_active:
            where["is_active"] = True

        return self.db.count(self.TABLE_NAME, where)

    def get_conversation_with_user_check(
        self,
        conversation_id: str,
        user_id: str,
        only_active: bool = True,
    ) -> Optional[Conversation]:
        """
        获取会话并检查用户权限

        Args:
            conversation_id: 会话ID
            user_id: 用户ID

        Returns:
            会话对象，如果不存在或用户无权限返回None
        """
        where = {"conversation_id": conversation_id, "user_id": user_id}
        if only_active:
            where["is_active"] = True

        result = self.db.select_one(
            table=self.TABLE_NAME,
            where=where
        )
        return self._dict_to_model(result, Conversation)

    def delete_user_conversations(self, user_id: str, soft_delete: bool = True) -> int:
        """
        删除用户的所有会话

        Args:
            user_id: 用户ID
            soft_delete: 是否软删除（默认True）

        Returns:
            删除的会话数量
        """
        if soft_delete:
            # 软删除：设置is_active=False
            sql = f"""
                UPDATE {self.TABLE_NAME}
                SET is_active = %s, updated_at = %s
                WHERE user_id = %s
            """
            affected_rows = self.db.execute_update(sql, (False, datetime.utcnow(), user_id))
            logger.info(f"User conversations soft deleted: user_id={user_id}, count={affected_rows}")
        else:
            # 硬删除：物理删除记录
            affected_rows = self.db.delete_one(
                table=self.TABLE_NAME,
                where={"user_id": user_id}
            )
            logger.info(f"User conversations hard deleted: user_id={user_id}, count={affected_rows}")

        return affected_rows


# 全局会话仓储实例
_conversation_repository: Optional[ConversationRepository] = None


def get_conversation_repository() -> ConversationRepository:
    """
    获取全局会话仓储实例（单例模式）

    Returns:
        ConversationRepository实例
    """
    global _conversation_repository

    if _conversation_repository is None:
        _conversation_repository = ConversationRepository()

    return _conversation_repository
