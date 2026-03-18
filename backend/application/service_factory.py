from __future__ import annotations

from typing import Optional

from backend.agents.file_processor.file_processor_agent import FileProcessorAgent
from backend.agents.retrieval.retrieval_agent import RetrievalAgent
from backend.application.services import (
    ChatExecutionApplicationService,
    ChatServiceSupport,
    ChatTurnPreparationApplicationService,
    DocumentQueryApplicationService,
    DocumentUploadApplicationService,
    DocumentVectorRebuildApplicationService,
    KnowledgeBaseCrudApplicationService,
    KnowledgeManagementApplicationService,
    KnowledgeSearchApplicationService,
    WorkflowApplicationService,
)
from backend.database.repositories.conversation_repository import get_conversation_repository
from backend.database.repositories.file_repository import get_file_repository
from backend.database.repositories.knowledge_base_repository import get_knowledge_base_repository
from backend.database.repositories.message_repository import get_message_repository
from backend.infrastructure.persistence import (
    ConversationRepositoryAdapter,
    FileRepositoryAdapter,
    KnowledgeBaseRepositoryAdapter,
    MessageRepositoryAdapter,
)
from backend.infrastructure.storage import LocalFileStorageGateway
from backend.workflows.workflow_executor import WorkflowExecutor


_file_processor_agent: Optional[FileProcessorAgent] = None


def get_file_processor_agent() -> FileProcessorAgent:
    global _file_processor_agent
    if _file_processor_agent is None:
        _file_processor_agent = FileProcessorAgent()
    return _file_processor_agent


def build_workflow_application_service() -> WorkflowApplicationService:
    return WorkflowApplicationService(workflow_executor=WorkflowExecutor())


def build_chat_service_support() -> ChatServiceSupport:
    return ChatServiceSupport(
        conversation_repo=ConversationRepositoryAdapter(repository=get_conversation_repository()),
        message_repo=MessageRepositoryAdapter(repository=get_message_repository()),
        knowledge_base_repo=KnowledgeBaseRepositoryAdapter(repository=get_knowledge_base_repository()),
    )


def build_chat_turn_preparation_application_service() -> ChatTurnPreparationApplicationService:
    return ChatTurnPreparationApplicationService(build_chat_service_support())


def build_chat_execution_application_service() -> ChatExecutionApplicationService:
    support_service = build_chat_service_support()
    preparation_service = ChatTurnPreparationApplicationService(support_service)
    return ChatExecutionApplicationService(
        workflow_service=build_workflow_application_service(),
        support_service=support_service,
        preparation_service=preparation_service,
    )


def _build_document_service_kwargs() -> dict:
    return {
        'file_repo': FileRepositoryAdapter(repository=get_file_repository()),
        'knowledge_base_repo': KnowledgeBaseRepositoryAdapter(repository=get_knowledge_base_repository()),
        'storage_gateway': LocalFileStorageGateway(),
        'processor_agent': get_file_processor_agent(),
    }


def build_document_upload_application_service() -> DocumentUploadApplicationService:
    return DocumentUploadApplicationService(**_build_document_service_kwargs())


def build_document_query_application_service() -> DocumentQueryApplicationService:
    return DocumentQueryApplicationService(**_build_document_service_kwargs())


def build_document_vector_rebuild_application_service() -> DocumentVectorRebuildApplicationService:
    return DocumentVectorRebuildApplicationService(**_build_document_service_kwargs())


def build_knowledge_base_crud_application_service() -> KnowledgeBaseCrudApplicationService:
    return KnowledgeBaseCrudApplicationService(
        knowledge_repo=KnowledgeBaseRepositoryAdapter(repository=get_knowledge_base_repository()),
        document_service=build_document_query_application_service(),
    )


def build_knowledge_search_application_service() -> KnowledgeSearchApplicationService:
    return KnowledgeSearchApplicationService(
        knowledge_repo=KnowledgeBaseRepositoryAdapter(repository=get_knowledge_base_repository()),
        retrieval_executor=RetrievalAgent(),
    )


def build_knowledge_management_application_service() -> KnowledgeManagementApplicationService:
    document_query_service = build_document_query_application_service()
    return KnowledgeManagementApplicationService(
        knowledge_base_crud_service=KnowledgeBaseCrudApplicationService(
            knowledge_repo=KnowledgeBaseRepositoryAdapter(repository=get_knowledge_base_repository()),
            document_service=document_query_service,
        ),
        knowledge_search_service=KnowledgeSearchApplicationService(
            knowledge_repo=KnowledgeBaseRepositoryAdapter(repository=get_knowledge_base_repository()),
            retrieval_executor=RetrievalAgent(),
        ),
        document_upload_service=build_document_upload_application_service(),
        document_query_service=document_query_service,
        document_vector_rebuild_service=build_document_vector_rebuild_application_service(),
    )
