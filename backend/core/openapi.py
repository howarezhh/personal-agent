"""OpenAPI customization helpers."""

from __future__ import annotations

import copy

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from backend.api.chat import AskResponse
from backend.contracts.responses import ErrorDetail, ErrorResponse, SuccessResponse
from backend.contracts.sse import SSEEvent


def _register_schema(components: dict, name: str, model) -> None:
    schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
    for definition_name, definition_schema in schema.pop("$defs", {}).items():
        components.setdefault(definition_name, definition_schema)
    components[name] = schema


def build_custom_openapi(app: FastAPI):
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
    _register_schema(components, "AskResponse", AskResponse)
    _register_schema(components, "SuccessResponse_AskResponse_", SuccessResponse[AskResponse])

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
            for status_code in ("400", "401", "403", "404", "422", "500"):
                responses.setdefault(status_code, copy.deepcopy(error_response_template))

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
                operation["x-sse-event-schema"] = {"$ref": "#/components/schemas/SSEEvent"}
                operation["x-stream-response"] = True

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

    app.openapi_schema = schema
    return schema
