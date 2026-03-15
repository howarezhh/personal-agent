"""OpenAPI 自定义增强模块。

该模块用于在 FastAPI 自动生成的 OpenAPI 文档基础上补充：
1. 统一的错误响应模型；
2. SSE 事件结构说明；
3. 聊天与内容生成接口的流式响应描述；
4. 泛型响应在 Schema 中的显式注册。
"""

from __future__ import annotations

import copy

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from backend.api.chat import AskResponse
from backend.contracts.responses import ErrorDetail, ErrorResponse, SuccessResponse
from backend.contracts.sse import SSEEvent


def _register_schema(components: dict, name: str, model) -> None:
    """将 Pydantic 模型注册到 OpenAPI components 中。

    Args:
        components: OpenAPI `components.schemas` 字典。
        name: 注册后的 Schema 名称。
        model: Pydantic 模型类或泛型实例。
    """
    schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
    # 将模型内部引用的子定义一并展开到 components 中，避免文档引用缺失。
    for definition_name, definition_schema in schema.pop("$defs", {}).items():
        components.setdefault(definition_name, definition_schema)
    components[name] = schema


def build_custom_openapi(app: FastAPI):
    """构建并缓存自定义 OpenAPI 文档。

    Args:
        app: FastAPI 应用实例。

    Returns:
        最终生成的 OpenAPI Schema。
    """
    if app.openapi_schema:
        return app.openapi_schema

    # 先基于 FastAPI 默认行为生成原始 Schema，再做统一增强。
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
    _register_schema(components, "AskResponse", AskResponse)
    _register_schema(components, "SuccessResponse_AskResponse_", SuccessResponse[AskResponse])

    # 统一错误响应模板，便于在多条路由中重复复用。
    error_response_template = {
        "description": "Unified error response",
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/ErrorResponse"}
            }
        },
    }

    for path, path_item in schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue

            responses = operation.setdefault("responses", {})
            # 为常见错误状态码补齐统一响应结构，减少前后端对错误格式的歧义。
            for status_code in ("400", "401", "403", "404", "422", "500"):
                responses.setdefault(status_code, copy.deepcopy(error_response_template))

            # 聊天接口同时支持普通 JSON 响应与 SSE 流式输出，因此需要在文档中显式声明两种 content-type。
            if path == "/api/v1/chat/ask" and method.lower() == "post":
                responses["200"] = {
                    "description": "Successful response or SSE stream",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/SuccessResponse_AskResponse_"}
                        },
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
                # 使用扩展字段补充 SSE 事件契约，方便前端和文档工具读取。
                operation["x-sse-event-schema"] = {"$ref": "#/components/schemas/SSEEvent"}
                operation["x-stream-response"] = True

            # 以下内容生成接口同样支持普通响应与流式响应，因此对 200 响应做同样的增强。
            if path in {
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
            } and method.lower() == "post":
                json_schema = responses.get("200", {}).get("content", {}).get("application/json", {}).get("schema")
                if json_schema:
                    responses["200"] = {
                        "description": "Successful response or SSE stream",
                        "content": {
                            "application/json": {
                                "schema": json_schema,
                            },
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

    # 将生成结果缓存到 app 上，避免重复计算。
    app.openapi_schema = schema
    return schema
