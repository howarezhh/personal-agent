# -*- coding: utf-8 -*-

"""Chat API module."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.api.app_services import (
    get_chat_execution_application_service,
    get_chat_runtime_application_service,
    get_chat_turn_preparation_application_service,
)
from backend.api.dependencies import get_current_user_id
from backend.contracts.api.chat import AskRequest, AskResponse, PauseRequest, PauseStreamResponse
from backend.contracts.errors import AppException, ErrorCode, forbidden, internal_server_error
from backend.contracts.responses import SuccessResponse
from backend.contracts.sse import build_sse_event
from backend.utils.logger import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.post("/pause", response_model=SuccessResponse[PauseStreamResponse])
async def pause_stream(request: PauseRequest, user_id: str = Depends(get_current_user_id)):
    runtime_service = get_chat_runtime_application_service()
    pause_result = await runtime_service.pause_stream(stream_id=request.stream_id, user_id=user_id)

    if not pause_result.get("exists"):
        return SuccessResponse.create(
            data={"stream_id": request.stream_id, "paused": False},
            message="Stream not found",
        )

    if not pause_result.get("authorized", True):
        raise forbidden(
            "You are not allowed to pause this stream",
            error_code=ErrorCode.SYSTEM_FORBIDDEN,
            error="ChatPauseForbidden",
        )

    task = pause_result.get("task")
    if task and not task.done():
        task.cancel()

    return SuccessResponse.create(
        data={"stream_id": request.stream_id, "paused": True},
        message="Chat stream paused",
    )


async def ask(
    request: AskRequest,
    user_id: str = Depends(get_current_user_id),
    http_request: Optional[Request] = None,
):
    try:
        request_id = getattr(getattr(http_request, "state", None), "request_id", None)
        preparation_service = get_chat_turn_preparation_application_service()
        execution_service = get_chat_execution_application_service()
        runtime_service = get_chat_runtime_application_service()
        turn = preparation_service.prepare_chat_turn(
            user_id=user_id,
            question=request.question,
            conversation_id=request.conversation_id,
            knowledge_base_id=request.knowledge_base_id,
            enable_knowledge_base=request.enable_knowledge_base,
            request_id=request_id,
            history_limit=runtime_service.get_history_limit(),
        )

        if request.stream:
            stream_id = f"{turn.conversation_id}:{turn.user_message_id}:{uuid4().hex[:8]}"
            return StreamingResponse(
                _stream_response(stream_id=stream_id, turn=turn),
                media_type="text/event-stream",
            )

        result = await execution_service.execute_non_stream_turn(turn=turn)
        return SuccessResponse.create(
            data=AskResponse(
                conversation_id=turn.conversation_id,
                message_id=turn.user_message_id,
                answer=result.get("answer", ""),
                execution_id=result.get("execution_id"),
                citations=result.get("citations", []),
            )
        )
    except AppException:
        raise
    except Exception as error:
        logger.error("Chat ask failed: %s", error, exc_info=True)
        raise internal_server_error(
            f"Chat execution failed: {error}",
            error_code=ErrorCode.CHAT_EXECUTION_FAILED,
            error="ChatExecutionFailed",
        )


@router.post("/ask")
async def ask_endpoint(
    http_request: Request,
    request: AskRequest,
    user_id: str = Depends(get_current_user_id),
):
    return await ask(request=request, user_id=user_id, http_request=http_request)


async def _stream_response(*, stream_id: str, turn):
    runtime_service = get_chat_runtime_application_service()
    current_task = asyncio.current_task()
    await runtime_service.register_stream(
        stream_id=stream_id,
        user_id=turn.user_id,
        conversation_id=turn.conversation_id,
        message_id=turn.user_message_id,
        task=current_task,
    )

    try:
        yield _format_sse_data(
            "thinking",
            "stream_started",
            request_id=turn.request_id,
            conversation_id=turn.conversation_id,
            message_id=turn.user_message_id,
            metadata={
                "stream_id": stream_id,
                "conversation_id": turn.conversation_id,
                "message_id": turn.user_message_id,
            },
            message="stream_started",
        )

        execution_service = get_chat_execution_application_service()
        async for event in execution_service.execute_stream_turn(turn=turn):
            yield _format_sse_data(
                event["event_type"],
                event["data"],
                request_id=turn.request_id,
                conversation_id=turn.conversation_id,
                message_id=turn.user_message_id,
                execution_id=event.get("execution_id"),
                metadata=event.get("metadata"),
            )
    except asyncio.CancelledError:
        yield _format_sse_data(
            "error",
            "Chat stream cancelled",
            request_id=turn.request_id,
            conversation_id=turn.conversation_id,
            message_id=turn.user_message_id,
            error_code=ErrorCode.CHAT_STREAM_ABORTED.value,
        )
        return
    except Exception as error:
        logger.error("Chat stream failed: %s", error, exc_info=True)
        yield _format_sse_data(
            "error",
            f"Chat stream failed: {error}",
            request_id=turn.request_id,
            conversation_id=turn.conversation_id,
            message_id=turn.user_message_id,
            error_code=ErrorCode.CHAT_EXECUTION_FAILED.value,
        )
    finally:
        await runtime_service.cleanup_stream(stream_id=stream_id)


def _extract_metadata_event_message(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    for key in ("message", "description", "event"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _extract_execution_id(payload: Any) -> Optional[str]:
    if isinstance(payload, dict) and payload.get("execution_id"):
        return str(payload["execution_id"])
    return None


def _format_sse_data(
    event_type: str,
    data: Any,
    *,
    request_id: Optional[str],
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    message: Optional[str] = None,
    error_code: Optional[str] = None,
) -> str:
    event_metadata = deepcopy(metadata) if metadata else {}
    if error_code:
        event_metadata.setdefault("error_code", error_code)

    payload_message = message
    if event_type == "metadata" and isinstance(data, dict):
        metadata_payload = deepcopy(data)
        metadata_payload.update(event_metadata)
        event_metadata = metadata_payload
        payload_message = payload_message or _extract_metadata_event_message(event_metadata)

    if payload_message is None and isinstance(data, str) and event_type in ("thinking", "error"):
        payload_message = data

    payload_content = data
    if event_type == "metadata":
        payload_content = None
    if event_type in ("thinking", "error") and isinstance(data, str):
        payload_content = None

    envelope_type = "thinking" if event_type == "metadata" else event_type
    event = build_sse_event(
        envelope_type,
        payload_content,
        message=payload_message,
        metadata=event_metadata,
        request_id=request_id,
        conversation_id=conversation_id,
        message_id=message_id,
        execution_id=execution_id or _extract_execution_id(data),
    )
    return f"event: {envelope_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
