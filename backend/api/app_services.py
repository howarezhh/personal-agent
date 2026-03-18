from __future__ import annotations

from backend.application.service_factory import (
    build_chat_execution_application_service,
    build_chat_turn_preparation_application_service,
    build_knowledge_management_application_service,
)
from backend.application.services import (
    AuthApplicationService,
    ChatExecutionApplicationService,
    ChatRuntimeApplicationService,
    ChatTurnPreparationApplicationService,
    ContentGenerationApplicationService,
    ConversationApplicationService,
    KnowledgeManagementApplicationService,
    RuntimeApplicationService,
    ToolApplicationService,
)


def get_auth_application_service() -> AuthApplicationService:
    return AuthApplicationService()


def get_chat_turn_preparation_application_service() -> ChatTurnPreparationApplicationService:
    return build_chat_turn_preparation_application_service()


def get_chat_execution_application_service() -> ChatExecutionApplicationService:
    return build_chat_execution_application_service()


def get_chat_runtime_application_service() -> ChatRuntimeApplicationService:
    return ChatRuntimeApplicationService()


def get_conversation_application_service() -> ConversationApplicationService:
    return ConversationApplicationService()


def get_content_generation_application_service() -> ContentGenerationApplicationService:
    return ContentGenerationApplicationService()


def get_knowledge_management_application_service() -> KnowledgeManagementApplicationService:
    return build_knowledge_management_application_service()


def get_runtime_application_service() -> RuntimeApplicationService:
    return RuntimeApplicationService()


def get_tool_application_service() -> ToolApplicationService:
    return ToolApplicationService()
