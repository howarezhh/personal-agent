# -*- coding: utf-8 -*-

"""内容生成 API 路由模块。"""

from __future__ import annotations

import inspect
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.api.app_services import get_content_generation_application_service
from backend.api.content_generation_route_specs import CONTENT_GENERATION_ROUTE_SPECS, ContentGenerationRouteSpec
from backend.api.dependencies import get_current_user
from backend.contracts.api.content_generation import ContentGenerationResponse
from backend.contracts.errors import AppException, ErrorCode, unauthorized
from backend.contracts.sse import build_sse_event
from backend.models.user import User
from backend.utils.logger import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/content", tags=["content_generation"])


def resolve_current_user_id(current_user: User | Dict[str, Any]) -> str:
    """解析并校验当前用户 ID。"""
    user_id = current_user.get("user_id") if isinstance(current_user, dict) else getattr(current_user, "user_id", None)
    if not user_id:
        raise unauthorized(
            "Invalid user identity",
            error_code=ErrorCode.AUTH_UNAUTHORIZED,
            error="InvalidUserIdentity",
        )
    return user_id


def _request_id(request: Request) -> str | None:
    """从请求上下文提取链路请求 ID。"""
    return getattr(getattr(request, "state", None), "request_id", None)


def _with_generation_id(data: Optional[Dict[str, Any]], generation_id: str) -> Dict[str, Any]:
    """为返回结果补齐生成记录 ID。"""
    payload = dict(data or {})
    payload["generation_id"] = generation_id
    return payload


def _format_content_sse_data(
    event_type: str,
    content: Any,
    *,
    request_id: Optional[str],
    metadata: Optional[Dict[str, Any]] = None,
    message: Optional[str] = None,
) -> str:
    """统一格式化内容生成 SSE 事件。"""
    event = build_sse_event(
        event_type,
        content,
        message=message,
        metadata=metadata or {},
        request_id=request_id,
    )
    return f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _stream_content_generation(
    *,
    request_id: Optional[str],
    user_id: str,
    content_type: str,
    action: str,
    input_params: Dict[str, Any],
    tool_name: str,
    tool_params: Dict[str, Any],
):
    """流式执行内容生成，并统一处理落库与 SSE 输出。"""
    service = get_content_generation_application_service()
    generation_id, start_time = await service.save_generation(
        user_id=user_id,
        content_type=content_type,
        action=action,
        input_params=input_params,
        tool_name=tool_name,
    )
    stream_metadata = {
        "generation_id": generation_id,
        "content_type": content_type,
        "action": action,
        "tool_name": tool_name,
    }

    try:
        yield _format_content_sse_data(
            "thinking",
            None,
            request_id=request_id,
            metadata=stream_metadata,
            message="stream_started",
        )

        final_result: Optional[Dict[str, Any]] = None
        async for event in service.execute_generation_stream(tool_name=tool_name, action=action, **tool_params):
            event_type = event.get("type")
            if event_type == "content":
                chunk = event.get("content") or ""
                if chunk:
                    yield _format_content_sse_data("content", chunk, request_id=request_id, metadata=stream_metadata)
            elif event_type == "result":
                final_result = {
                    "success": True,
                    "data": _with_generation_id(event.get("data"), generation_id),
                    "error": None,
                }
                yield _format_content_sse_data("result", final_result["data"], request_id=request_id, metadata=stream_metadata)
            elif event_type == "error":
                final_result = {
                    "success": False,
                    "data": None,
                    "error": str(event.get("error") or "Streaming generation failed"),
                }
                break

        if not final_result:
            final_result = {"success": False, "data": None, "error": "Streaming generation returned no result"}

        await service.update_generation_result(
            generation_id=generation_id,
            start_time_ms=start_time,
            result=final_result,
        )

        if final_result.get("success"):
            yield _format_content_sse_data("done", final_result.get("data"), request_id=request_id, metadata=stream_metadata)
            return

        yield _format_content_sse_data(
            "error",
            None,
            request_id=request_id,
            metadata=stream_metadata,
            message=str(final_result.get("error") or "Streaming generation failed"),
        )
    except Exception as error:
        error_message = str(error)
        logger.error("Content generation stream failed: %s", error_message, exc_info=True)
        await service.update_generation_result(
            generation_id=generation_id,
            start_time_ms=start_time,
            result={"success": False, "data": None, "error": error_message},
        )
        yield _format_content_sse_data("error", None, request_id=request_id, metadata=stream_metadata, message=error_message)


async def _handle_content_generation_request(
    *,
    http_request: Request,
    current_user: User | Dict[str, Any],
    stream: bool,
    content_type: str,
    action: str,
    input_params: Dict[str, Any],
    tool_name: str,
    tool_params: Dict[str, Any],
    log_label: str,
):
    """统一处理内容生成的同步与流式调用。"""
    service = get_content_generation_application_service()
    generation_id: Optional[str] = None
    start_time: Optional[int] = None

    try:
        current_user_id = resolve_current_user_id(current_user)
        if stream:
            return StreamingResponse(
                _stream_content_generation(
                    request_id=_request_id(http_request),
                    user_id=current_user_id,
                    content_type=content_type,
                    action=action,
                    input_params=input_params,
                    tool_name=tool_name,
                    tool_params=tool_params,
                ),
                media_type="text/event-stream",
            )

        logger.info("%s user_id=%s action=%s", log_label, current_user_id, action)
        generation_id, start_time = await service.save_generation(
            user_id=current_user_id,
            content_type=content_type,
            action=action,
            input_params=input_params,
            tool_name=tool_name,
        )
        result = await service.execute_generation_tool(tool_name=tool_name, action=action, **tool_params)
        await service.update_generation_result(
            generation_id=generation_id,
            start_time_ms=start_time,
            result=result,
        )

        if result.get("success"):
            result["data"] = _with_generation_id(result.get("data"), generation_id)

        return ContentGenerationResponse(**result)
    except AppException as error:
        if generation_id and start_time:
            await service.update_generation_result(
                generation_id=generation_id,
                start_time_ms=start_time,
                result={"success": False, "data": None, "error": str(error)},
            )
        raise
    except Exception as error:
        logger.error("%s failed: %s", log_label, error, exc_info=True)
        error_result = {"success": False, "data": None, "error": str(error)}
        if generation_id and start_time:
            await service.update_generation_result(
                generation_id=generation_id,
                start_time_ms=start_time,
                result=error_result,
            )
        return ContentGenerationResponse(**error_result)


def _build_content_generation_endpoint(route_spec: ContentGenerationRouteSpec):
    """根据路由规格动态生成 FastAPI 端点。"""

    async def _content_generation_endpoint(**kwargs):
        # 这里统一将 FastAPI 注入参数映射到共享处理函数，避免每个端点重复样板代码。
        http_request: Request = kwargs["http_request"]
        request_model = kwargs["request"]
        stream: bool = kwargs.get("stream", False)
        current_user: User | Dict[str, Any] = kwargs["current_user"]
        action = route_spec.resolve_action(request_model)

        return await _handle_content_generation_request(
            http_request=http_request,
            current_user=current_user,
            stream=stream,
            content_type=route_spec.content_type,
            action=action,
            input_params=request_model.model_dump(),
            tool_name=route_spec.tool_name,
            tool_params=route_spec.build_tool_params(request_model),
            log_label=route_spec.log_label,
        )

    _content_generation_endpoint.__name__ = route_spec.endpoint_name
    _content_generation_endpoint.__qualname__ = route_spec.endpoint_name
    _content_generation_endpoint.__doc__ = route_spec.description
    _content_generation_endpoint.__signature__ = inspect.Signature(
        parameters=[
            inspect.Parameter("http_request", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Request),
            inspect.Parameter("request", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=route_spec.request_model),
            inspect.Parameter("stream", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=False, annotation=bool),
            inspect.Parameter(
                "current_user",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=Depends(get_current_user),
                annotation=User | Dict[str, Any],
            ),
        ],
        return_annotation=ContentGenerationResponse,
    )
    return _content_generation_endpoint


def _register_content_generation_routes() -> None:
    """按规格批量注册内容生成路由，保证路由配置单一事实源。"""
    for route_spec in CONTENT_GENERATION_ROUTE_SPECS:
        router.add_api_route(
            route_spec.path,
            _build_content_generation_endpoint(route_spec),
            methods=["POST"],
            response_model=ContentGenerationResponse,
            summary=route_spec.summary,
            description=route_spec.description,
        )


_register_content_generation_routes()
