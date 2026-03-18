from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Literal, Mapping, Optional, get_args, get_origin
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import PydanticUndefined


AGENT_IO_PROTOCOL_VERSION = "2.0.0"

AgentExecutionStatus = Literal["success", "failed", "partial"]


class WorkflowContextSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_results: Dict[str, Any] = Field(default_factory=dict)
    step_config: Dict[str, Any] = Field(default_factory=dict)
    previous_output: Optional[Dict[str, Any]] = None


class AgentInputSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "protocol_version": AGENT_IO_PROTOCOL_VERSION,
                "user_id": "user_123",
                "conversation_id": "conv_123",
                "message_id": "msg_123",
                "content": "请总结这份资料",
                "request_id": "req_123",
                "execution_id": "exec_parent_123",
                "knowledge_base_id": "kb_123",
                "document_id": "doc_123",
                "enable_knowledge_base": True,
                "conversation_history": [{"role": "user", "content": "上一轮问题"}],
                "route_decision": {"action": "retrieval"},
                "retrieval_results": [{"id": "chunk_1", "content": "知识片段"}],
                "tool_results": [{"tool_name": "weather", "success": True}],
                "metadata": {"debug": True},
                "workflow_context": {
                    "step_results": {},
                    "step_config": {},
                    "previous_output": None,
                },
            }
        },
    )

    protocol_version: str = Field(default=AGENT_IO_PROTOCOL_VERSION)
    user_id: str
    conversation_id: str
    message_id: Optional[str] = None
    content: str
    request_id: Optional[str] = None
    execution_id: Optional[str] = None
    knowledge_base_id: Optional[str] = None
    document_id: Optional[str] = None
    enable_knowledge_base: Optional[bool] = None
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    route_decision: Optional[Dict[str, Any]] = None
    retrieval_results: List[Dict[str, Any]] = Field(default_factory=list)
    tool_results: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    workflow_context: Optional[WorkflowContextSchema] = None


class RouterAgentInputSchema(AgentInputSchema):
    available_agents: List[str] = Field(default_factory=list)


class RetrievalAgentInputSchema(AgentInputSchema):
    vector_search_filter: Dict[str, Any] = Field(default_factory=dict)
    top_k: int = 5
    enable_rerank: bool = True
    rerank_top_k: Optional[int] = None
    keyword_top_k: Optional[int] = None
    enable_exact_phrase: Optional[bool] = None
    enable_sparse_keyword: Optional[bool] = None
    enable_dense_vector: Optional[bool] = None
    enable_fusion_rank: Optional[bool] = None


class GenerationAgentInputSchema(AgentInputSchema):
    context: Optional[str] = None
    sources: List[Dict[str, Any]] = Field(default_factory=list)


class ToolAgentInputSchema(AgentInputSchema):
    available_tools: List[str] = Field(default_factory=list)
    tool_timeout: Optional[int] = None
    tool_name: Optional[str] = None
    tool_params: Dict[str, Any] = Field(default_factory=dict)


class FileProcessorAgentInputSchema(AgentInputSchema):
    file_id: Optional[str] = None
    file_path: Optional[str] = None
    file_type: Optional[str] = None
    file_metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentOutputSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "protocol_version": AGENT_IO_PROTOCOL_VERSION,
                "execution_id": "exec_123",
                "agent_name": "router_agent",
                "agent_type": "router",
                "content": "",
                "status": "success",
                "error_message": None,
                "execution_time_ms": 38,
                "request_id": "req_123",
                "conversation_id": "conv_123",
                "message_id": "msg_123",
                "knowledge_base_id": "kb_123",
                "document_id": None,
                "route_decision": {"action": "retrieval"},
                "retrieval_results": [],
                "tool_result": None,
                "metadata": {"debug": True},
            }
        },
    )

    protocol_version: str = Field(default=AGENT_IO_PROTOCOL_VERSION)
    execution_id: str
    agent_name: str
    agent_type: str
    content: str = ""
    status: AgentExecutionStatus = "success"
    error_message: Optional[str] = None
    execution_time_ms: int = 0
    request_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    knowledge_base_id: Optional[str] = None
    document_id: Optional[str] = None
    route_decision: Optional[Dict[str, Any]] = None
    retrieval_results: List[Dict[str, Any]] = Field(default_factory=list)
    tool_result: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RouterAgentOutputSchema(AgentOutputSchema):
    confidence: Optional[float] = None
    reasoning: Optional[str] = None
    suggested_agents: List[str] = Field(default_factory=list)
    suggested_tools: List[str] = Field(default_factory=list)


class RetrievalAgentOutputSchema(AgentOutputSchema):
    rewrite_info: Optional[Dict[str, Any]] = None


class GenerationAgentOutputSchema(AgentOutputSchema):
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    has_hallucination: bool = False
    token_count: Optional[int] = None


class ToolAgentOutputSchema(AgentOutputSchema):
    tool_name: Optional[str] = None
    tool_params: Dict[str, Any] = Field(default_factory=dict)
    interpreted_result: Optional[Dict[str, Any]] = None
    tool_call_id: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    no_tool_needed: Optional[bool] = None
    reasoning: Optional[str] = None
    route_action: Optional[str] = None
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0


class FileProcessorAgentOutputSchema(AgentOutputSchema):
    file_id: Optional[str] = None
    chunk_count: Optional[int] = None
    summary: Optional[str] = None
    extracted_text: Optional[str] = None
    extracted_images: List[str] = Field(default_factory=list)
    extracted_tables: List[Dict[str, Any]] = Field(default_factory=list)
    file_metadata: Dict[str, Any] = Field(default_factory=dict)
    page_count: Optional[int] = None


_INPUT_SCHEMA_BY_NAME = {
    "AgentInput": AgentInputSchema,
    "AgentInputSchema": AgentInputSchema,
    "RouterAgentInput": RouterAgentInputSchema,
    "RouterAgentInputSchema": RouterAgentInputSchema,
    "RetrievalAgentInput": RetrievalAgentInputSchema,
    "RetrievalAgentInputSchema": RetrievalAgentInputSchema,
    "GenerationAgentInput": GenerationAgentInputSchema,
    "GenerationAgentInputSchema": GenerationAgentInputSchema,
    "ToolAgentInput": ToolAgentInputSchema,
    "ToolAgentInputSchema": ToolAgentInputSchema,
    "FileProcessorAgentInput": FileProcessorAgentInputSchema,
    "FileProcessorAgentInputSchema": FileProcessorAgentInputSchema,
}

_OUTPUT_SCHEMA_BY_NAME = {
    "AgentOutput": AgentOutputSchema,
    "AgentOutputSchema": AgentOutputSchema,
    "RouterAgentOutput": RouterAgentOutputSchema,
    "RouterAgentOutputSchema": RouterAgentOutputSchema,
    "RetrievalAgentOutput": RetrievalAgentOutputSchema,
    "RetrievalAgentOutputSchema": RetrievalAgentOutputSchema,
    "GenerationAgentOutput": GenerationAgentOutputSchema,
    "GenerationAgentOutputSchema": GenerationAgentOutputSchema,
    "ToolAgentOutput": ToolAgentOutputSchema,
    "ToolAgentOutputSchema": ToolAgentOutputSchema,
    "FileProcessorAgentOutput": FileProcessorAgentOutputSchema,
    "FileProcessorAgentOutputSchema": FileProcessorAgentOutputSchema,
}

_AGENT_INPUT_REQUIRED_DEFAULTS = {
    "protocol_version": AGENT_IO_PROTOCOL_VERSION,
    "user_id": "",
    "conversation_id": "",
    "content": "",
}

_AGENT_OUTPUT_REQUIRED_DEFAULTS = {
    "protocol_version": AGENT_IO_PROTOCOL_VERSION,
    "execution_id": lambda: str(uuid4()),
    "agent_name": "",
    "agent_type": "",
}


def _build_default_value(default_value: Any) -> Any:
    return default_value() if callable(default_value) else deepcopy(default_value)


def _resolve_runtime_name(runtime_cls_or_name: Any) -> str:
    if isinstance(runtime_cls_or_name, str):
        return runtime_cls_or_name.split(".")[-1]
    if isinstance(runtime_cls_or_name, type):
        return runtime_cls_or_name.__name__
    return type(runtime_cls_or_name).__name__


def _extract_model_cls(annotation: Any) -> Optional[type[BaseModel]]:
    origin = get_origin(annotation)
    if origin is None:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return annotation
        return None

    for arg in get_args(annotation):
        nested_model_cls = _extract_model_cls(arg)
        if nested_model_cls is not None:
            return nested_model_cls
    return None


def _has_default_factory(field_info: Any) -> bool:
    default_factory = getattr(field_info, "default_factory", None)
    return default_factory is not None and default_factory is not PydanticUndefined


def _filter_payload_for_schema(payload: Mapping[str, Any], schema_cls: type[BaseModel]) -> Dict[str, Any]:
    filtered_payload: Dict[str, Any] = {}
    for field_name, field_info in schema_cls.model_fields.items():
        if field_name not in payload:
            continue

        value = payload[field_name]
        if value is None and _has_default_factory(field_info):
            continue

        nested_model_cls = _extract_model_cls(field_info.annotation)
        if nested_model_cls is not None:
            if value is None:
                filtered_payload[field_name] = None
                continue
            if isinstance(value, BaseModel):
                filtered_payload[field_name] = value.model_dump(mode="python")
                continue
            if isinstance(value, Mapping):
                filtered_payload[field_name] = _normalize_model_payload(value, nested_model_cls)
                continue
            continue

        filtered_payload[field_name] = deepcopy(value)

    return filtered_payload


def _apply_schema_defaults(
    payload: Dict[str, Any],
    schema_cls: type[BaseModel],
    runtime_required_defaults: Mapping[str, Any],
) -> Dict[str, Any]:
    normalized_payload = deepcopy(payload)

    for field_name, field_info in schema_cls.model_fields.items():
        if field_name in normalized_payload and normalized_payload[field_name] is not None:
            continue

        if field_name in runtime_required_defaults:
            normalized_payload[field_name] = _build_default_value(runtime_required_defaults[field_name])
            continue

        if _has_default_factory(field_info):
            normalized_payload[field_name] = field_info.default_factory()
            continue

        if field_info.default is not PydanticUndefined:
            normalized_payload[field_name] = deepcopy(field_info.default)

    return normalized_payload


def _normalize_model_payload(
    payload: Mapping[str, Any],
    schema_cls: type[BaseModel],
    runtime_required_defaults: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    filtered_payload = _filter_payload_for_schema(payload, schema_cls)
    normalized_payload = _apply_schema_defaults(
        filtered_payload,
        schema_cls,
        runtime_required_defaults or {},
    )
    return schema_cls.model_validate(normalized_payload).model_dump(mode="python")


def get_agent_input_schema_cls(runtime_cls_or_name: Any) -> type[BaseModel]:
    runtime_name = _resolve_runtime_name(runtime_cls_or_name)
    return _INPUT_SCHEMA_BY_NAME.get(runtime_name, AgentInputSchema)


def get_agent_output_schema_cls(runtime_cls_or_name: Any) -> type[BaseModel]:
    runtime_name = _resolve_runtime_name(runtime_cls_or_name)
    return _OUTPUT_SCHEMA_BY_NAME.get(runtime_name, AgentOutputSchema)


def normalize_workflow_context_payload(payload: Any) -> Optional[Dict[str, Any]]:
    if payload is None:
        return None
    if isinstance(payload, WorkflowContextSchema):
        return payload.model_dump(mode="python")
    if not isinstance(payload, Mapping):
        return None
    return _normalize_model_payload(payload, WorkflowContextSchema)


def normalize_agent_input_payload(payload: Any, runtime_cls_or_name: Any = AgentInputSchema) -> Dict[str, Any]:
    working_payload = payload if isinstance(payload, Mapping) else {}
    schema_cls = get_agent_input_schema_cls(runtime_cls_or_name)
    return _normalize_model_payload(
        working_payload,
        schema_cls,
        runtime_required_defaults=_AGENT_INPUT_REQUIRED_DEFAULTS,
    )


def normalize_agent_output_payload(payload: Any, runtime_cls_or_name: Any = AgentOutputSchema) -> Dict[str, Any]:
    working_payload = payload if isinstance(payload, Mapping) else {}
    schema_cls = get_agent_output_schema_cls(runtime_cls_or_name)
    return _normalize_model_payload(
        working_payload,
        schema_cls,
        runtime_required_defaults=_AGENT_OUTPUT_REQUIRED_DEFAULTS,
    )


__all__ = [
    "AGENT_IO_PROTOCOL_VERSION",
    "AgentExecutionStatus",
    "WorkflowContextSchema",
    "AgentInputSchema",
    "RouterAgentInputSchema",
    "RetrievalAgentInputSchema",
    "GenerationAgentInputSchema",
    "ToolAgentInputSchema",
    "FileProcessorAgentInputSchema",
    "AgentOutputSchema",
    "RouterAgentOutputSchema",
    "RetrievalAgentOutputSchema",
    "GenerationAgentOutputSchema",
    "ToolAgentOutputSchema",
    "FileProcessorAgentOutputSchema",
    "get_agent_input_schema_cls",
    "get_agent_output_schema_cls",
    "normalize_workflow_context_payload",
    "normalize_agent_input_payload",
    "normalize_agent_output_payload",
]
