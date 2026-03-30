"""OpenAPI 自定义增强模块。

该模块用于在 FastAPI 自动生成的 OpenAPI 文档基础上补充：
1. 统一的错误响应模型；
2. SSE 事件结构说明；
3. 内容生成与任务运行时接口的流式响应描述；
4. 关键 DTO 在 components 中的显式注册。
"""

from __future__ import annotations

import copy

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from backend.contracts.agent_io import (
    AgentInputSchema,
    AgentOutputSchema,
    FileProcessorAgentInputSchema,
    FileProcessorAgentOutputSchema,
    GenerationAgentInputSchema,
    GenerationAgentOutputSchema,
    RetrievalAgentInputSchema,
    RetrievalAgentOutputSchema,
    ToolAgentInputSchema,
    ToolAgentOutputSchema,
    WorkflowContextSchema,
)
from backend.contracts.api.task_runtime import (
    TaskRuntimeActionRequest,
    TaskRuntimeActionResponse,
    TaskRuntimeArtifactResponse,
    TaskRuntimeCheckpointResponse,
    TaskRuntimeEvaluationReportResponse,
    TaskRuntimeExecutionSummaryResponse,
    TaskRuntimeGoalResponse,
    TaskRuntimePlanResponse,
    TaskRuntimePlanStepResponse,
    TaskRuntimePrepareResponse,
    TaskRuntimeStatusResponse,
    TaskRuntimeSubmitRequest,
)
from backend.contracts.responses import ErrorDetail, ErrorResponse
from backend.contracts.sse import SSEEvent, StreamChunkSchema


def _register_schema(components: dict, name: str, model) -> None:
    """将 Pydantic 模型注册到 OpenAPI components 中。"""
    schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
    for definition_name, definition_schema in schema.pop("$defs", {}).items():
        components.setdefault(definition_name, definition_schema)
    components[name] = schema


def build_custom_openapi(app: FastAPI):
    """构建并缓存自定义 OpenAPI 文档。"""
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    components = schema.setdefault("components", {}).setdefault("schemas", {})
    _register_schema(components, "ErrorDetail", ErrorDetail)
    _register_schema(components, "ErrorResponse", ErrorResponse)
    _register_schema(components, "SSEEvent", SSEEvent)
    _register_schema(components, "StreamChunkSchema", StreamChunkSchema)
    _register_schema(components, "WorkflowContextSchema", WorkflowContextSchema)
    _register_schema(components, "AgentInputSchema", AgentInputSchema)
    _register_schema(components, "RetrievalAgentInputSchema", RetrievalAgentInputSchema)
    _register_schema(components, "GenerationAgentInputSchema", GenerationAgentInputSchema)
    _register_schema(components, "ToolAgentInputSchema", ToolAgentInputSchema)
    _register_schema(components, "FileProcessorAgentInputSchema", FileProcessorAgentInputSchema)
    _register_schema(components, "AgentOutputSchema", AgentOutputSchema)
    _register_schema(components, "RetrievalAgentOutputSchema", RetrievalAgentOutputSchema)
    _register_schema(components, "GenerationAgentOutputSchema", GenerationAgentOutputSchema)
    _register_schema(components, "ToolAgentOutputSchema", ToolAgentOutputSchema)
    _register_schema(components, "FileProcessorAgentOutputSchema", FileProcessorAgentOutputSchema)
    _register_schema(components, "TaskRuntimeSubmitRequest", TaskRuntimeSubmitRequest)
    _register_schema(components, "TaskRuntimeActionRequest", TaskRuntimeActionRequest)
    _register_schema(components, "TaskRuntimeExecutionSummaryResponse", TaskRuntimeExecutionSummaryResponse)
    _register_schema(components, "TaskRuntimeGoalResponse", TaskRuntimeGoalResponse)
    _register_schema(components, "TaskRuntimePlanStepResponse", TaskRuntimePlanStepResponse)
    _register_schema(components, "TaskRuntimePlanResponse", TaskRuntimePlanResponse)
    _register_schema(components, "TaskRuntimeCheckpointResponse", TaskRuntimeCheckpointResponse)
    _register_schema(components, "TaskRuntimeArtifactResponse", TaskRuntimeArtifactResponse)
    _register_schema(components, "TaskRuntimeEvaluationReportResponse", TaskRuntimeEvaluationReportResponse)
    _register_schema(components, "TaskRuntimePrepareResponse", TaskRuntimePrepareResponse)
    _register_schema(components, "TaskRuntimeStatusResponse", TaskRuntimeStatusResponse)
    _register_schema(components, "TaskRuntimeActionResponse", TaskRuntimeActionResponse)

    error_response_template = {
        "description": "Unified error response",
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/ErrorResponse"}
            }
        },
    }

    content_stream_paths = {
        "/api/v1/content/novel/outline",
        "/api/v1/content/novel/chapter",
        "/api/v1/content/novel/character",
        "/api/v1/content/novel/worldview",
        "/api/v1/content/novel/continue",
        "/api/v1/content/script/outline",
        "/api/v1/content/script/scene",
        "/api/v1/content/script/dialogue",
        "/api/v1/content/script/storyboard",
        "/api/v1/content/script/complete",
        "/api/v1/content/optimize",
    }

    for path, path_item in schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue

            responses = operation.setdefault("responses", {})
            for status_code in ("400", "401", "403", "404", "422", "500"):
                responses.setdefault(status_code, copy.deepcopy(error_response_template))

            if path in content_stream_paths and method.lower() == "post":
                json_schema = responses.get("200", {}).get("content", {}).get("application/json", {}).get("schema")
                if json_schema:
                    responses["200"] = {
                        "description": "Successful response or SSE stream",
                        "content": {
                            "application/json": {"schema": json_schema},
                            "text/event-stream": {
                                "schema": {"type": "string"},
                                "examples": {
                                    "stream": {
                                        "summary": "SSE stream",
                                        "value": 'event: content\ndata: {"type":"content","content":"hello"}\n\n',
                                    }
                                },
                            },
                        },
                    }
                    operation["x-sse-event-schema"] = {"$ref": "#/components/schemas/SSEEvent"}
                    operation["x-stream-response"] = True

            if path == "/api/v1/task-runtime/tasks/stream" and method.lower() == "post":
                responses["200"] = {
                    "description": "Task runtime SSE stream",
                    "content": {
                        "text/event-stream": {
                            "schema": {"type": "string"},
                            "examples": {
                                "planning": {
                                    "summary": "规划阶段事件",
                                    "value": 'event: result\ndata: {"type":"result","content":{"plan_id":"plan_xxx"},"metadata":{"stage":"planning","request_id":"req_xxx","conversation_id":"conv_xxx","message_id":"msg_xxx","execution_id":"exec_xxx","plan_id":"plan_xxx","step_id":null},"timestamp":"2026-03-23T00:00:00Z","request_id":"req_xxx","conversation_id":"conv_xxx","message_id":"msg_xxx","execution_id":"exec_xxx"}\n\n',
                                },
                                "error": {
                                    "summary": "统一错误事件",
                                    "value": 'event: error\ndata: {"type":"error","message":"任务执行失败：下游组件异常","content":null,"metadata":{"stage":"termination","request_id":"req_xxx","conversation_id":"conv_xxx","message_id":"msg_xxx","execution_id":"exec_xxx","plan_id":null,"step_id":null,"error_code":"WORKFLOW_EXECUTION_ERROR"},"timestamp":"2026-03-23T00:00:01Z","request_id":"req_xxx","conversation_id":"conv_xxx","message_id":"msg_xxx","execution_id":"exec_xxx","error_code":"WORKFLOW_EXECUTION_ERROR"}\n\n',
                                }
                            },
                        }
                    },
                }
                operation["x-sse-event-schema"] = {"$ref": "#/components/schemas/SSEEvent"}
                operation["x-stream-response"] = True
                operation["x-runtime-stage-field"] = "metadata.stage"
                operation["x-runtime-stages"] = [
                    "goal_parsing",
                    "planning",
                    "step_started",
                    "step_observation",
                    "step_evaluation",
                    "goal_evaluation",
                    "replan",
                    "termination",
                ]

            if path == "/api/v1/task-runtime/tasks" and method.lower() == "post":
                operation["x-task-lifecycle-enabled"] = True
                operation["x-task-follow-up-paths"] = [
                    "/api/v1/task-runtime/tasks/{task_id}",
                    "/api/v1/task-runtime/tasks/{task_id}/pause",
                    "/api/v1/task-runtime/tasks/{task_id}/resume",
                    "/api/v1/task-runtime/tasks/{task_id}/cancel",
                    "/api/v1/task-runtime/tasks/{task_id}/retry",
                ]

            if path == "/api/v1/task-runtime/tasks/{task_id}" and method.lower() == "get":
                operation["x-task-status-contract"] = {
                    "$ref": "#/components/schemas/TaskRuntimeStatusResponse"
                }
                operation["x-task-status-values"] = [
                    "pending",
                    "running",
                    "paused",
                    "succeeded",
                    "failed",
                    "cancelled",
                    "timed_out",
                ]

            if path in {
                "/api/v1/task-runtime/tasks/{task_id}/pause",
                "/api/v1/task-runtime/tasks/{task_id}/resume",
                "/api/v1/task-runtime/tasks/{task_id}/cancel",
                "/api/v1/task-runtime/tasks/{task_id}/retry",
            } and method.lower() == "post":
                operation["x-task-action-request-schema"] = {
                    "$ref": "#/components/schemas/TaskRuntimeActionRequest"
                }
                operation["x-task-action-response-schema"] = {
                    "$ref": "#/components/schemas/TaskRuntimeActionResponse"
                }

    app.openapi_schema = schema
    return schema
