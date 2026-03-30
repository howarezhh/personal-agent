from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from backend.agents.base.agent_input import AgentInput
from backend.infrastructure.persistence import (
    ConversationRepositoryAdapter,
    KnowledgeBaseRepositoryAdapter,
    MessageRepositoryAdapter,
)
from backend.models.conversation import ConversationCreate
from backend.models.message import MessageCreate
from backend.utils.citation_utils import normalize_message_content_with_citations, replace_citation_placeholders


@dataclass
class PreparedChatTurn:
    """聊天主链路准备完成后的中间对象。"""

    user_id: str
    question: str
    conversation_id: str
    user_message_id: str
    conversation_history: list[dict[str, Any]]
    request_id: Optional[str]
    enable_knowledge_base: bool
    knowledge_base_id: Optional[str]


class ChatServiceSupport:
    """聊天应用服务共享支持层，统一承接仓储访问与消息持久化。"""

    def __init__(self, conversation_repo=None, message_repo=None, knowledge_base_repo=None):
        self.conversation_repo = conversation_repo or ConversationRepositoryAdapter()
        self.message_repo = message_repo or MessageRepositoryAdapter()
        self.knowledge_base_repo = knowledge_base_repo or KnowledgeBaseRepositoryAdapter()

    def ensure_conversation(self, *, user_id: str, conversation_id: Optional[str], question: str):
        """确保当前请求拥有可用会话；若未传会话则创建新会话。"""
        if conversation_id:
            conversation = self.conversation_repo.get_conversation_with_user_check(
                conversation_id=conversation_id,
                user_id=user_id,
            )
            return conversation, conversation_id

        conversation = self.conversation_repo.create_conversation(
            ConversationCreate(
                user_id=user_id,
                title=question[:50] + ("..." if len(question) > 50 else ""),
            )
        )
        return conversation, conversation.conversation_id

    def ensure_knowledge_base(self, *, user_id: str, knowledge_base_id: Optional[str]):
        """校验知识库归属；未传知识库时直接跳过。"""
        if not knowledge_base_id:
            return None
        return self.knowledge_base_repo.get_by_id_for_user(knowledge_base_id, user_id)

    def get_history(self, *, conversation_id: str, limit: int):
        """读取并规范化历史消息，统一处理引用占位符。"""
        history = self.message_repo.get_conversation_history(conversation_id=conversation_id, limit=limit)
        for message in history:
            if message.message_type == "assistant":
                message.content = normalize_message_content_with_citations(
                    message.content,
                    getattr(message, "metadata", None),
                )
        return history, [
            {"role": "user" if msg.message_type == "user" else "assistant", "content": msg.content}
            for msg in history
        ]

    def save_user_message(
        self,
        *,
        conversation_id: str,
        question: str,
        metadata: dict[str, Any] | None = None,
        message_id: str | None = None,
    ):
        """持久化用户消息，并在传入 `message_id` 时提供幂等复用能力。"""
        if message_id:
            existing_message = self.message_repo.get_message_by_id(message_id)
            if existing_message is not None:
                return existing_message

        sequence_number = self.message_repo.get_next_sequence_number(conversation_id)
        message = self.message_repo.create_message(
            MessageCreate(
                message_id=message_id,
                conversation_id=conversation_id,
                message_type="user",
                content=question,
                sequence_number=sequence_number,
                metadata=metadata,
            )
        )
        self.conversation_repo.update_message_count(conversation_id, increment=1)
        return message

    def build_agent_input(
        self,
        *,
        user_id: str,
        conversation_id: str,
        user_message_id: str,
        question: str,
        conversation_history: list[dict[str, Any]],
        enable_knowledge_base: bool,
        knowledge_base_id: Optional[str],
        request_id: Optional[str] = None,
    ) -> AgentInput:
        """构造统一 AgentInput，供工作流执行层消费。"""
        return AgentInput(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=user_message_id,
            content=question,
            request_id=request_id,
            knowledge_base_id=knowledge_base_id,
            enable_knowledge_base=enable_knowledge_base,
            conversation_history=conversation_history,
            metadata={},
        )

    def save_assistant_message(
        self,
        *,
        conversation_id: str,
        content: str,
        citations: list[Any],
        parent_message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        """持久化助手消息，并统一补齐引用元数据与时间戳更新。"""
        if not content:
            return None

        normalized_content = replace_citation_placeholders(content, citations)
        message_metadata = {"citations": citations} if citations else {}
        if metadata:
            message_metadata.update(metadata)

        sequence_number = self.message_repo.get_next_sequence_number(conversation_id)
        message = self.message_repo.create_message(
            MessageCreate(
                conversation_id=conversation_id,
                message_type="assistant",
                content=normalized_content,
                sequence_number=sequence_number,
                parent_message_id=parent_message_id,
                metadata=message_metadata or None,
            )
        )
        self.conversation_repo.update_message_count(conversation_id, increment=1)
        self.conversation_repo.update_conversation_timestamp(conversation_id)
        return message
