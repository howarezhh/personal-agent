from __future__ import annotations

from typing import Optional

from backend.agents.base.agent_input import AgentInput
from backend.application.services.chat_service_support import ChatServiceSupport, PreparedChatTurn
from backend.contracts.errors import ErrorCode, not_found


class ChatTurnPreparationApplicationService:
    """聊天轮次准备服务，负责会话、知识库与历史消息预处理。"""

    def __init__(self, support_service: ChatServiceSupport):
        self.support_service = support_service

    def prepare_chat_turn(
        self,
        *,
        user_id: str,
        question: str,
        conversation_id: Optional[str],
        knowledge_base_id: Optional[str],
        enable_knowledge_base: bool,
        request_id: Optional[str],
        history_limit: int,
    ) -> PreparedChatTurn:
        """组装聊天轮次执行前的完整上下文。"""
        conversation, resolved_conversation_id = self.support_service.ensure_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
            question=question,
        )
        if not conversation:
            raise not_found(
                "Conversation not found",
                error_code=ErrorCode.CONVERSATION_NOT_FOUND,
                error="ConversationNotFound",
            )

        effective_enable_knowledge_base = bool(enable_knowledge_base)
        if knowledge_base_id:
            knowledge_base = self.support_service.ensure_knowledge_base(
                user_id=user_id,
                knowledge_base_id=knowledge_base_id,
            )
            if not knowledge_base:
                raise not_found(
                    "Knowledge base not found",
                    error_code=ErrorCode.KNOWLEDGE_BASE_NOT_FOUND,
                    error="KnowledgeNotFound",
                )
            effective_enable_knowledge_base = True

        _, history_list = self.support_service.get_history(
            conversation_id=resolved_conversation_id,
            limit=history_limit,
        )
        user_message = self.support_service.save_user_message(
            conversation_id=resolved_conversation_id,
            question=question,
            metadata={
                "request_id": request_id,
                "conversation_id": resolved_conversation_id,
                "knowledge_base_id": knowledge_base_id,
            },
        )

        return PreparedChatTurn(
            user_id=user_id,
            question=question,
            conversation_id=resolved_conversation_id,
            user_message_id=user_message.message_id,
            conversation_history=history_list,
            request_id=request_id,
            enable_knowledge_base=effective_enable_knowledge_base,
            knowledge_base_id=knowledge_base_id,
        )

    def build_agent_input_for_turn(self, turn: PreparedChatTurn) -> AgentInput:
        """将准备结果映射为工作流层可直接消费的 AgentInput。"""
        return self.support_service.build_agent_input(
            user_id=turn.user_id,
            conversation_id=turn.conversation_id,
            user_message_id=turn.user_message_id,
            question=turn.question,
            conversation_history=turn.conversation_history,
            enable_knowledge_base=turn.enable_knowledge_base,
            knowledge_base_id=turn.knowledge_base_id,
            request_id=turn.request_id,
        )

