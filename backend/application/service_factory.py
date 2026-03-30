from __future__ import annotations

from typing import Optional

from backend.agents.file_processor.file_processor_agent import FileProcessorAgent
from backend.agents.retrieval.retrieval_agent import RetrievalAgent
from backend.application.task_runtime import TaskRuntimeEventTranslator
from backend.application.task_runtime.agent_step_executor import AgentStepExecutor
from backend.application.task_runtime.default_components import (
    HeuristicPlanner,
    RuleBasedGoalJudge,
    RuleBasedGoalParser,
    RuleBasedReplanner,
    RuleBasedStepEvaluator,
)
from backend.application.task_runtime.llm_components import build_task_runtime_llm_bundle
from backend.application.task_runtime.task_controller import TaskController
from backend.application.services import (
    AgentExecutionApplicationService,
    ChatServiceSupport,
    ChatTurnPreparationApplicationService,
    ContentGenerationApplicationService,
    DocumentQueryApplicationService,
    DocumentUploadApplicationService,
    DocumentVectorRebuildApplicationService,
    KnowledgeBaseCrudApplicationService,
    KnowledgeManagementApplicationService,
    KnowledgeSearchApplicationService,
    RetrievalPersistenceApplicationService,
    RuntimeApplicationService,
    TaskRuntimeApplicationService,
    ToolApplicationService,
)
from backend.core.config_manager import get_config_manager
from backend.database.repositories.agent_execution_repository import get_agent_execution_repository
from backend.database.repositories.conversation_repository import get_conversation_repository
from backend.database.repositories.file_repository import get_file_repository
from backend.database.repositories.knowledge_base_repository import get_knowledge_base_repository
from backend.database.repositories.message_repository import get_message_repository
from backend.database.repositories.retrieval_result_repository import get_retrieval_result_repository
from backend.database.repositories.task_runtime_repository import get_task_runtime_repository
from backend.database.repositories.tool_call_repository import get_tool_call_repository
from backend.infrastructure.persistence import (
    ConversationRepositoryAdapter,
    DatabaseGatewayAdapter,
    FileRepositoryAdapter,
    KnowledgeBaseRepositoryAdapter,
    MessageRepositoryAdapter,
)
from backend.infrastructure.persistence.content_generation_record_store import ContentGenerationRecordStore
from backend.infrastructure.storage import LocalFileStorageGateway
from backend.infrastructure.vector_store import EmbeddingGatewayAdapter, VectorStoreGatewayAdapter
from backend.tools import get_all_tools, get_tool
from backend.tools.tool_config import get_tool_config
from backend.tools.tool_initializer import close_initialized_tool_clients, initialize_tools
from backend.tools.tool_registry import get_tool_registry


_file_processor_agent: Optional[FileProcessorAgent] = None


def get_file_processor_agent() -> FileProcessorAgent:
    global _file_processor_agent
    if _file_processor_agent is None:
        _file_processor_agent = FileProcessorAgent()
    return _file_processor_agent


def build_chat_service_support() -> ChatServiceSupport:
    return ChatServiceSupport(
        conversation_repo=ConversationRepositoryAdapter(repository=get_conversation_repository()),
        message_repo=MessageRepositoryAdapter(repository=get_message_repository()),
        knowledge_base_repo=KnowledgeBaseRepositoryAdapter(repository=get_knowledge_base_repository()),
    )


def build_chat_turn_preparation_application_service() -> ChatTurnPreparationApplicationService:
    return ChatTurnPreparationApplicationService(build_chat_service_support())


def _build_document_service_kwargs() -> dict:
    return {
        'file_repo': FileRepositoryAdapter(repository=get_file_repository()),
        'knowledge_base_repo': KnowledgeBaseRepositoryAdapter(repository=get_knowledge_base_repository()),
        'storage_gateway': LocalFileStorageGateway(),
        'processor_agent': get_file_processor_agent(),
        'vector_store': VectorStoreGatewayAdapter(),
        'db_manager': DatabaseGatewayAdapter(),
    }


def _build_document_query_service_kwargs() -> dict:
    return {
        'file_repo': FileRepositoryAdapter(repository=get_file_repository()),
        'knowledge_base_repo': KnowledgeBaseRepositoryAdapter(repository=get_knowledge_base_repository()),
        'storage_gateway': LocalFileStorageGateway(),
        'processor_agent': None,
        'vector_store': VectorStoreGatewayAdapter(),
        'db_manager': DatabaseGatewayAdapter(),
    }


def build_document_upload_application_service() -> DocumentUploadApplicationService:
    return DocumentUploadApplicationService(**_build_document_service_kwargs())


def build_document_query_application_service() -> DocumentQueryApplicationService:
    return DocumentQueryApplicationService(**_build_document_query_service_kwargs())


def build_document_vector_rebuild_application_service() -> DocumentVectorRebuildApplicationService:
    return DocumentVectorRebuildApplicationService(
        **_build_document_service_kwargs(),
        embedding_gateway=EmbeddingGatewayAdapter(),
    )


def build_knowledge_base_crud_application_service() -> KnowledgeBaseCrudApplicationService:
    return KnowledgeBaseCrudApplicationService(
        knowledge_repo=KnowledgeBaseRepositoryAdapter(repository=get_knowledge_base_repository()),
        document_service=None,
    )


def build_knowledge_search_application_service() -> KnowledgeSearchApplicationService:
    return KnowledgeSearchApplicationService(
        knowledge_repo=KnowledgeBaseRepositoryAdapter(repository=get_knowledge_base_repository()),
        retrieval_executor=RetrievalAgent(),
    )


def build_knowledge_management_application_service() -> KnowledgeManagementApplicationService:
    return KnowledgeManagementApplicationService(
        knowledge_base_crud_service=build_knowledge_base_crud_application_service(),
    )


def build_agent_execution_application_service() -> AgentExecutionApplicationService:
    return AgentExecutionApplicationService(repository=get_agent_execution_repository())


def build_retrieval_persistence_application_service() -> RetrievalPersistenceApplicationService:
    return RetrievalPersistenceApplicationService(
        database_manager=DatabaseGatewayAdapter(),
        retrieval_result_repository=get_retrieval_result_repository(),
    )


def build_tool_application_service() -> ToolApplicationService:
    return ToolApplicationService(
        execution_repo=get_agent_execution_repository(),
        tool_call_repo=get_tool_call_repository(),
        tool_registry=get_tool_registry(),
        tool_resolver=get_tool,
        tool_catalog_provider=get_all_tools,
        tool_config=get_tool_config(),
    )


def build_content_generation_application_service() -> ContentGenerationApplicationService:
    return ContentGenerationApplicationService(
        store=ContentGenerationRecordStore(database_manager=DatabaseGatewayAdapter()),
        tool_provider=get_tool,
    )


def build_runtime_application_service() -> RuntimeApplicationService:
    return RuntimeApplicationService(
        config_manager=get_config_manager(),
        database_gateway=DatabaseGatewayAdapter(),
        tool_initializer=initialize_tools,
        tool_client_closer=close_initialized_tool_clients,
    )


def build_task_runtime_application_service() -> TaskRuntimeApplicationService:
    """构建任务运行时应用服务。"""
    config_manager = get_config_manager()
    common_agent_config = config_manager.get("agent.common", {}) or {}
    try:
        max_iterations = max(1, int(common_agent_config.get("max_iterations", 8)))
    except (TypeError, ValueError):
        max_iterations = 8

    task_runtime_config = config_manager.get("agent.task_runtime", {}) or {}
    try:
        prepared_session_ttl_seconds = max(1, int(task_runtime_config.get("prepared_session_ttl_seconds", 300)))
    except (TypeError, ValueError):
        prepared_session_ttl_seconds = 300

    # 生产装配默认优先挂载 LLM 主链路；若模型运行时初始化失败，则由 bundle 内部按配置优雅回退。
    llm_bundle = build_task_runtime_llm_bundle(config_manager=config_manager)

    # 这里保持控制器主循环不变，仅将步骤执行统一收敛到 Agent 适配层，避免前后端链路分叉。
    task_controller = TaskController(
        goal_parser=llm_bundle.goal_parser if llm_bundle is not None else RuleBasedGoalParser(),
        planner=llm_bundle.planner if llm_bundle is not None else HeuristicPlanner(),
        step_executor=AgentStepExecutor(),
        step_evaluator=llm_bundle.step_evaluator if llm_bundle is not None else RuleBasedStepEvaluator(),
        goal_judge=llm_bundle.goal_judge if llm_bundle is not None else RuleBasedGoalJudge(),
        replanner=llm_bundle.replanner if llm_bundle is not None else RuleBasedReplanner(),
        max_iterations=max_iterations,
    )
    return TaskRuntimeApplicationService(
        task_controller=task_controller,
        event_translator=TaskRuntimeEventTranslator(),
        task_runtime_repository=get_task_runtime_repository(),
        chat_service_support=build_chat_service_support(),
        prepared_session_ttl_seconds=prepared_session_ttl_seconds,
    )
