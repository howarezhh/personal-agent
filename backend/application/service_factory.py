"""Application service factories to keep API routes infrastructure-agnostic."""

from __future__ import annotations

from typing import Optional

from backend.agents.file_processor.file_processor_agent import FileProcessorAgent
from backend.application.services import (
    ChatApplicationService,
    DocumentApplicationService,
    KnowledgeBaseApplicationService,
    WorkflowApplicationService,
)
from backend.database.repositories.file_repository import get_file_repository
from backend.database.repositories.knowledge_base_repository import get_knowledge_base_repository
from backend.database.repositories.conversation_repository import get_conversation_repository
from backend.database.repositories.message_repository import get_message_repository
from backend.infrastructure.persistence import (
    ConversationRepositoryAdapter,
    FileRepositoryAdapter,
    KnowledgeBaseRepositoryAdapter,
    MessageRepositoryAdapter,
)
from backend.infrastructure.storage import LocalFileStorageGateway
from backend.infrastructure.vector_store import EmbeddingGatewayAdapter, VectorStoreGatewayAdapter
from backend.workflows.workflow_executor import WorkflowExecutor


_file_processor_agent: Optional[FileProcessorAgent] = None


def get_file_processor_agent() -> FileProcessorAgent:
    global _file_processor_agent
    if _file_processor_agent is None:
        _file_processor_agent = FileProcessorAgent()
    return _file_processor_agent


def build_workflow_application_service() -> WorkflowApplicationService:
    return WorkflowApplicationService(workflow_executor=WorkflowExecutor())


def build_chat_application_service() -> ChatApplicationService:
    return ChatApplicationService(
        workflow_service=build_workflow_application_service(),
        conversation_repo=ConversationRepositoryAdapter(repository=get_conversation_repository()),
        message_repo=MessageRepositoryAdapter(repository=get_message_repository()),
        knowledge_base_repo=KnowledgeBaseRepositoryAdapter(repository=get_knowledge_base_repository()),
    )


def build_document_application_service() -> DocumentApplicationService:
    return DocumentApplicationService(
        file_repo=FileRepositoryAdapter(repository=get_file_repository()),
        knowledge_base_repo=KnowledgeBaseRepositoryAdapter(repository=get_knowledge_base_repository()),
        storage_gateway=LocalFileStorageGateway(),
        processor_agent=get_file_processor_agent(),
    )


def build_knowledge_application_service() -> KnowledgeBaseApplicationService:
    return KnowledgeBaseApplicationService(
        knowledge_repo=KnowledgeBaseRepositoryAdapter(repository=get_knowledge_base_repository()),
        document_service=build_document_application_service(),
        embedding_gateway=EmbeddingGatewayAdapter(),
        vector_store=VectorStoreGatewayAdapter(),
    )
