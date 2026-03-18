from __future__ import annotations

from importlib import import_module


_SERVICE_MODULES = {
    'AuthApplicationService': 'backend.application.services.auth_application_service',
    'ChatExecutionApplicationService': 'backend.application.services.chat_execution_application_service',
    'ChatRuntimeApplicationService': 'backend.application.services.chat_runtime_application_service',
    'ChatServiceSupport': 'backend.application.services.chat_service_support',
    'ChatTurnPreparationApplicationService': 'backend.application.services.chat_turn_preparation_application_service',
    'ContentGenerationApplicationService': 'backend.application.services.content_generation_application_service',
    'ConversationApplicationService': 'backend.application.services.conversation_application_service',
    'DocumentQueryApplicationService': 'backend.application.services.document_query_application_service',
    'DocumentUploadApplicationService': 'backend.application.services.document_upload_application_service',
    'DocumentVectorRebuildApplicationService': 'backend.application.services.document_vector_rebuild_application_service',
    'DocumentServiceSupport': 'backend.application.services.document_service_support',
    'KnowledgeBaseCrudApplicationService': 'backend.application.services.knowledge_base_crud_application_service',
    'KnowledgeBaseServiceSupport': 'backend.application.services.knowledge_base_service_support',
    'KnowledgeSearchApplicationService': 'backend.application.services.knowledge_search_application_service',
    'KnowledgeManagementApplicationService': 'backend.application.services.knowledge_management_application_service',
    'RuntimeApplicationService': 'backend.application.services.runtime_application_service',
    'ToolApplicationService': 'backend.application.services.tool_application_service',
    'WorkflowApplicationService': 'backend.application.services.workflow_application_service',
}

__all__ = list(_SERVICE_MODULES.keys())


def __getattr__(name: str):
    if name not in _SERVICE_MODULES:
        raise AttributeError(name)
    module = import_module(_SERVICE_MODULES[name])
    return getattr(module, name)
