from __future__ import annotations

from backend.application.service_factory import (
    build_chat_turn_preparation_application_service,
    build_content_generation_application_service,
    build_knowledge_management_application_service,
    build_runtime_application_service,
    build_task_runtime_application_service,
    build_tool_application_service,
)
from backend.application.services import (
    AuthApplicationService,
    ChatRuntimeApplicationService,
    ChatTurnPreparationApplicationService,
    ContentGenerationApplicationService,
    ConversationApplicationService,
    KnowledgeManagementApplicationService,
    RuntimeApplicationService,
    TaskRuntimeApplicationService,
    ToolApplicationService,
)


_knowledge_management_application_service: KnowledgeManagementApplicationService | None = None
_task_runtime_application_service: TaskRuntimeApplicationService | None = None


def get_auth_application_service() -> AuthApplicationService:
    return AuthApplicationService()


def get_chat_turn_preparation_application_service() -> ChatTurnPreparationApplicationService:
    return build_chat_turn_preparation_application_service()


def get_chat_runtime_application_service() -> ChatRuntimeApplicationService:
    return ChatRuntimeApplicationService()


def get_conversation_application_service() -> ConversationApplicationService:
    return ConversationApplicationService()


def get_content_generation_application_service() -> ContentGenerationApplicationService:
    return build_content_generation_application_service()


def get_knowledge_management_application_service() -> KnowledgeManagementApplicationService:
    global _knowledge_management_application_service
    if _knowledge_management_application_service is None:
        _knowledge_management_application_service = build_knowledge_management_application_service()
    return _knowledge_management_application_service


def get_runtime_application_service() -> RuntimeApplicationService:
    return build_runtime_application_service()


def get_task_runtime_application_service() -> TaskRuntimeApplicationService:
    global _task_runtime_application_service
    if _task_runtime_application_service is None:
        _task_runtime_application_service = build_task_runtime_application_service()
    return _task_runtime_application_service


def get_tool_application_service() -> ToolApplicationService:
    return build_tool_application_service()
