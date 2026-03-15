import json
import re
import asyncio
from copy import deepcopy
from typing import Optional, Any, Dict, TypedDict
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Depends, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from backend.api.dependencies import get_current_user_id
from backend.api.models import SuccessResponse, ErrorResponse
from backend.application.service_factory import build_chat_application_service
from backend.application.services import ChatApplicationService
from backend.contracts.errors import ErrorCode
from backend.contracts.sse import build_sse_event
from backend.core.config_manager import get_config_manager
from backend.utils.logger import get_logger
from backend.utils.citation_utils import replace_citation_placeholders


logger = get_logger(__name__)


class NonStreamChatResult(TypedDict, total=False):
    answer: str
    execution_id: Optional[str]
    assistant_message_id: Optional[str]


def get_chat_application_service() -> ChatApplicationService:
    return build_chat_application_service()

# 创建路由器
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=5000, description="用户问题")
    conversation_id: Optional[str] = Field(None, description="会话ID（可选，不提供则创建新会话）")
    stream: bool = Field(default=True, description="是否使用流式输出")
    enable_knowledge_base: bool = Field(default=False, description="是否启用知识库增强")
    knowledge_base_id: Optional[str] = Field(default=None, description="Selected knowledge base ID")


class PauseRequest(BaseModel):
    stream_id: str = Field(..., min_length=1, description="流式会话ID")

class PauseStreamResponse(BaseModel):
    stream_id: str = Field(..., description="流式会话 ID")
    paused: bool = Field(..., description="是否已暂停")


active_streams: Dict[str, Dict[str, Any]] = {}
active_streams_lock = asyncio.Lock()


def _get_chat_history_limit() -> int:
    config_manager = get_config_manager()
    history_config = config_manager.get("conversation_history", {}) or {}
    raw_limit = history_config.get("max_history_length", 10)
    try:
        return max(1, int(raw_limit))
    except (TypeError, ValueError):
        return 10


class AskResponse(BaseModel):
    conversation_id: str = Field(..., description="会话ID")
    message_id: str = Field(..., description="消息ID")
    answer: str = Field(..., description="助手回答")
    execution_id: Optional[str] = Field(None, description="执行ID")

@router.post("/pause", response_model=SuccessResponse[PauseStreamResponse])
async def pause_stream(
    request: PauseRequest,
    user_id: str = Depends(get_current_user_id)
):
    logger.info(f"[CHAT-PAUSE] 收到暂停请求: user_id={user_id}, stream_id={request.stream_id}")

    task = None
    async with active_streams_lock:
        stream_context = active_streams.get(request.stream_id)
        if not stream_context:
            logger.info(f"[CHAT-PAUSE] 流式会话不存在或已结束: stream_id={request.stream_id}")
            return SuccessResponse.create(
                data={"stream_id": request.stream_id, "paused": False},
                message="对话已结束或不存在"
            )

        if stream_context.get("user_id") != user_id:
            logger.warning(f"[CHAT-PAUSE] 无权暂停该流式会话: user_id={user_id}, stream_id={request.stream_id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权暂停该对话"
            )

        stream_context["paused"] = True
        task = stream_context.get("task")
        logger.info(f"[CHAT-PAUSE] 已标记为暂停: stream_id={request.stream_id}")

    if task and not task.done():
        task.cancel()
        logger.info(f"[CHAT-PAUSE] 已取消后台任务: stream_id={request.stream_id}")

    return SuccessResponse.create(
        data={"stream_id": request.stream_id, "paused": True},
        message="已暂停对话"
    )


def _summarize_payload(payload: Any) -> str:
    if payload is None:
        return "None"

    if isinstance(payload, dict):
        keys = list(payload.keys())
        return f"dict(keys={keys[:8]}{'...' if len(keys) > 8 else ''})"

    if isinstance(payload, list):
        item_type = type(payload[0]).__name__ if payload else "empty"
        return f"list(len={len(payload)}, item_type={item_type})"

    if isinstance(payload, str):
        preview = payload.replace("\n", "\\n")
        if len(preview) > 120:
            preview = preview[:120] + "..."
        return f"str(len={len(payload)}, preview='{preview}')"

    return f"{type(payload).__name__}"


async def ask(
    request: AskRequest,
    user_id: str = Depends(get_current_user_id),
    http_request: Optional[Request] = None,
):
    try:
        logger.info(f"[CHAT] 收到用户提问: user_id={user_id}, question={request.question[:50]}...")
        logger.info(f"[CHAT] request params: conversation_id={request.conversation_id}, stream={request.stream}, enable_knowledge_base={request.enable_knowledge_base}, knowledge_base_id={request.knowledge_base_id}")
        app_service = get_chat_application_service()

        # 1. 创建或获取会话
        conversation, conversation_id = app_service.ensure_conversation(
            user_id=user_id,
            conversation_id=request.conversation_id,
            question=request.question,
        )
        if not conversation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在或访问被拒绝")

        # 2. 获取对话历史（在保存用户消息之前获取，避免包含当前消息）
        logger.debug("[CHAT] 获取对话历史")
        if request.knowledge_base_id:
            knowledge_base = app_service.ensure_knowledge_base(user_id=user_id, knowledge_base_id=request.knowledge_base_id)
            if not knowledge_base:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="知识库不存在或无权访问"
                )
            request.enable_knowledge_base = True

        conversation_history, history_list = app_service.get_history(conversation_id=conversation_id, limit=_get_chat_history_limit())
        logger.debug(f"[CHAT] 获取到{len(conversation_history)}条历史消息")

        # 3. 保存用户消息到数据库
        logger.info("[CHAT] 保存用户消息")
        request_id = getattr(getattr(http_request, "state", None), "request_id", None)
        user_message = app_service.save_user_message(
            conversation_id=conversation_id,
            question=request.question,
            metadata={
                "request_id": request_id,
                "conversation_id": conversation_id,
                "knowledge_base_id": request.knowledge_base_id,
            },
        )
        logger.info(f"[CHAT] 用户消息保存成功: message_id={user_message.message_id}")

        # 4. 根据是否流式返回不同响应
        if request.stream:
            logger.info("[CHAT] 使用流式响应")
            # 流式响应
            stream_id = f"{conversation_id}:{user_message.message_id}:{uuid4().hex[:8]}"
            logger.info(f"[CHAT] stream_id={stream_id}")
            return StreamingResponse(
                _stream_response(
                    stream_id=stream_id,
                    request_id=request_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    user_message_id=user_message.message_id,
                    question=request.question,
                    conversation_history=history_list,
                    enable_knowledge_base=request.enable_knowledge_base,
                    knowledge_base_id=request.knowledge_base_id
                ),
                media_type="text/event-stream"
            )
        else:
            logger.info("[CHAT] 使用非流式响应")
            # 非流式响应
            result = await _non_stream_response(
                request_id=request_id,
                user_id=user_id,
                conversation_id=conversation_id,
                user_message_id=user_message.message_id,
                question=request.question,
                conversation_history=history_list,
                enable_knowledge_base=request.enable_knowledge_base,
                knowledge_base_id=request.knowledge_base_id
            )

            return SuccessResponse.create(
                data=AskResponse(
                    conversation_id=conversation_id,
                    message_id=user_message.message_id,
                    answer=result.get("answer", ""),
                    execution_id=result.get("execution_id"),
                )
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CHAT] 处理失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"处理问题失败: {str(e)}"
        )


@router.post("/ask")
async def ask_endpoint(
    http_request: Request,
    request: AskRequest,
    user_id: str = Depends(get_current_user_id),
):
    return await ask(request=request, user_id=user_id, http_request=http_request)


async def _stream_response(
    stream_id: str,
    request_id: Optional[str],
    user_id: str,
    conversation_id: str,
    user_message_id: str,
    question: str,
    conversation_history: list,
    enable_knowledge_base: bool = False,
    knowledge_base_id: Optional[str] = None
):
    current_task = asyncio.current_task()
    async with active_streams_lock:
        active_streams[stream_id] = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message_id": user_message_id,
            "task": current_task,
            "paused": False,
        }

    try:
        logger.info("[CHAT-STREAM] ========== 开始生成流式响应 ==========")
        app_service = get_chat_application_service()
        logger.info(f"[CHAT-STREAM] 用户ID: {user_id}")
        logger.info(f"[CHAT-STREAM] 会话ID: {conversation_id}")
        logger.info(f"[CHAT-STREAM] 消息ID: {user_message_id}")
        logger.info(f"[CHAT-STREAM] stream metadata prepared: stream_id={stream_id}")
        yield _format_sse_data(
            "thinking",
            "stream_started",
            request_id=request_id,
            conversation_id=conversation_id,
            message_id=user_message_id,
            metadata={
                "stream_id": stream_id,
                "conversation_id": conversation_id,
                "message_id": user_message_id,
            },
            message="stream_started",
        )
        logger.info(f"[CHAT-STREAM] 问题: {question[:100]}...")
        logger.info(f"[CHAT-STREAM] 历史消息数量: {len(conversation_history)}")
        logger.info(f"[CHAT-STREAM] 知识库开关: {enable_knowledge_base}")

        logger.debug("[CHAT-STREAM] 获取仓储实例")
        logger.debug("[CHAT-STREAM] 仓储实例获取成功")

        logger.debug("[CHAT-STREAM] 构建智能体输入")
        agent_input = app_service.build_agent_input(
            user_id=user_id,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            question=question,
            conversation_history=conversation_history,
            enable_knowledge_base=enable_knowledge_base,
            knowledge_base_id=knowledge_base_id,
            request_id=request_id,
        )
        logger.debug("[CHAT-STREAM] 智能体输入构建完成")

        # 使用工作流执行器
        logger.info("[CHAT-STREAM] 创建工作流执行器")
        logger.info("[CHAT-STREAM] 工作流执行器创建成功")

        full_answer = ""
        citations = []
        execution_id = None
        assistant_message_id = None

        # 执行工作流
        logger.info("[CHAT-STREAM] 开始执行工作流")
        async for chunk in app_service.workflow_service.execute_stream(agent_input):
            if chunk.chunk_type in ("tool_call", "result", "error"):
                logger.info(
                    "[CHAT-STREAM][TRACE] workflow_chunk: "
                    f"type={chunk.chunk_type}, payload={_summarize_payload(chunk.content)}"
                )

            if chunk.chunk_type == "thinking":
                logger.debug(f"[CHAT-STREAM] 思考步骤: {chunk.content}")
                yield _format_sse_data(
                    "thinking",
                    chunk.content,
                    request_id=request_id,
                    conversation_id=conversation_id,
                    message_id=user_message_id,
                    execution_id=_extract_execution_id(chunk),
                )

            elif chunk.chunk_type == "content":
                full_answer += chunk.content
                yield _format_sse_data(
                    "content",
                    chunk.content,
                    request_id=request_id,
                    conversation_id=conversation_id,
                    message_id=user_message_id,
                    execution_id=_extract_execution_id(chunk),
                )

            elif chunk.chunk_type == "tool_call":
                logger.info(f"[CHAT-STREAM] 工具调用: {chunk.content}")
                yield _format_sse_data(
                    "tool_call",
                    _build_sse_event_payload(chunk),
                    request_id=request_id,
                    conversation_id=conversation_id,
                    message_id=user_message_id,
                    execution_id=_extract_execution_id(chunk),
                )

            elif chunk.chunk_type == "result":
                logger.info(
                    "[CHAT-STREAM][TRACE] result_payload="
                    f"{_summarize_payload(chunk.content)}"
                )
                result_payload = _build_sse_event_payload(chunk)
                execution_id = _extract_execution_id(chunk) or _extract_execution_id(result_payload) or execution_id
                if isinstance(result_payload, dict) and "citations" in result_payload:
                    citations = result_payload.get("citations", [])
                    logger.info(f"[CHAT-STREAM] 获取到{len(citations)}条引用")
                yield _format_sse_data(
                    "result",
                    result_payload,
                    request_id=request_id,
                    conversation_id=conversation_id,
                    message_id=user_message_id,
                    execution_id=execution_id,
                )

            elif chunk.chunk_type == "error":
                logger.error(f"[CHAT-STREAM] 错误: {chunk.content}")
                yield _format_sse_data(
                    "error",
                    chunk.content,
                    request_id=request_id,
                    conversation_id=conversation_id,
                    message_id=user_message_id,
                    execution_id=_extract_execution_id(chunk) or execution_id,
                )
                return

        logger.info("[CHAT-STREAM] 工作流执行完成")

        normalized_answer = replace_citation_placeholders(full_answer, citations)

        # 保存助手回复
        if normalized_answer:
            logger.info("[CHAT-STREAM] 保存助手回复")
            assistant_message = app_service.save_assistant_message(
                conversation_id=conversation_id,
                content=normalized_answer,
                citations=citations,
                parent_message_id=user_message_id,
                metadata={
                    "request_id": request_id,
                    "conversation_id": conversation_id,
                    "execution_id": execution_id,
                    "knowledge_base_id": knowledge_base_id,
                },
            )
            assistant_message_id = assistant_message.message_id
            logger.info(f"[CHAT-STREAM] 助手消息保存成功: message_id={assistant_message.message_id}")
            logger.debug("[CHAT-STREAM] 会话时间戳已更新")

        logger.info("[CHAT-STREAM] 发送完成信号")
        done_payload = {
            "conversation_id": conversation_id,
            "assistant_message_id": assistant_message_id,
            "citations": citations
        }
        logger.info(
            "[CHAT-STREAM][TRACE] done_payload="
            f"{_summarize_payload(done_payload)}"
        )
        yield _format_sse_data(
            "done",
            done_payload,
            request_id=request_id,
            conversation_id=conversation_id,
            message_id=user_message_id,
            execution_id=execution_id,
        )

        logger.info("[CHAT-STREAM] ========== 流式响应生成完成 ==========")

    except asyncio.CancelledError:
        logger.info(f"[CHAT-STREAM] 流式会话已取消: stream_id={stream_id}")
        yield _format_sse_data(
            "error",
            "对话已取消",
            request_id=request_id,
            conversation_id=conversation_id,
            message_id=user_message_id,
            execution_id=execution_id,
            error_code=ErrorCode.CHAT_STREAM_ABORTED.value,
        )
        return
    except Exception as e:
        logger.error(f"[CHAT-STREAM] 流式响应失败: {str(e)}", exc_info=True)
        yield _format_sse_data(
            "error",
            f"生成回答失败: {str(e)}",
            request_id=request_id,
            conversation_id=conversation_id,
            message_id=user_message_id,
            execution_id=execution_id,
        )
    finally:
        async with active_streams_lock:
            active_streams.pop(stream_id, None)
        logger.info(f"[CHAT-STREAM] 流式会话已清理: stream_id={stream_id}")


async def _non_stream_response(
    user_id: str,
    conversation_id: str,
    user_message_id: str,
    question: str,
    conversation_history: list,
    enable_knowledge_base: bool = False,
    knowledge_base_id: Optional[str] = None,
    request_id: Optional[str] = None
) -> NonStreamChatResult:
    try:
        logger.info("[CHAT-NON-STREAM] 开始生成非流式回答")
        logger.info(f"[CHAT-NON-STREAM] 知识库开关: {enable_knowledge_base}")
        app_service = get_chat_application_service()

        agent_input = app_service.build_agent_input(
            user_id=user_id,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            question=question,
            conversation_history=conversation_history,
            enable_knowledge_base=enable_knowledge_base,
            knowledge_base_id=knowledge_base_id,
            request_id=request_id,
        )

        full_answer = ""
        citations = []
        execution_id = None
        assistant_message_id = None

        async for chunk in app_service.workflow_service.execute_stream(agent_input):
            if chunk.chunk_type == "content":
                full_answer += chunk.content
            elif chunk.chunk_type == "result":
                if isinstance(chunk.content, dict) and "citations" in chunk.content:
                    citations = chunk.content.get("citations", [])
                execution_id = _extract_execution_id(chunk.content) or execution_id
            elif chunk.chunk_type == "error":
                raise Exception(chunk.content)
            execution_id = _extract_execution_id(chunk) or execution_id

        normalized_answer = replace_citation_placeholders(full_answer, citations)

        if normalized_answer:
            assistant_message = app_service.save_assistant_message(
                conversation_id=conversation_id,
                content=normalized_answer,
                citations=citations,
                parent_message_id=user_message_id,
                metadata={
                    "request_id": request_id,
                    "conversation_id": conversation_id,
                    "execution_id": execution_id,
                    "knowledge_base_id": knowledge_base_id,
                },
            )
            assistant_message_id = assistant_message.message_id
            logger.info(f"[CHAT-NON-STREAM] 助手消息保存成功: message_id={assistant_message.message_id}")

        logger.info("[CHAT-NON-STREAM] 非流式回答生成完成")
        return {
            "answer": normalized_answer,
            "execution_id": execution_id,
            "assistant_message_id": assistant_message_id,
        }

    except Exception as e:
        logger.error(f"[CHAT-NON-STREAM] 非流式回答生成失败: {str(e)}", exc_info=True)
        raise


def _format_sse_data(
    event_type: str,
    data: Any,
    *,
    request_id: Optional[str] = None,
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
    if payload_message is None and isinstance(data, str) and event_type in ("thinking", "error"):
        payload_message = data

    payload_content = data
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
    data_str = json.dumps(event, ensure_ascii=False)
    return f"event: {event_type}\ndata: {data_str}\n\n"


def _build_sse_event_payload(chunk: Any) -> Any:
    if chunk.chunk_type == "tool_call":
        payload = deepcopy(chunk.metadata) if chunk.metadata else {}
        if chunk.content and "message" not in payload:
            payload["message"] = chunk.content
        return payload or chunk.content

    if chunk.chunk_type == "result":
        if isinstance(chunk.content, dict):
            payload = deepcopy(chunk.content)
        else:
            payload = {"content": chunk.content}

        if chunk.metadata:
            payload.setdefault("metadata", deepcopy(chunk.metadata))

        return payload

    if chunk.chunk_type == "metadata":
        if chunk.metadata:
            return deepcopy(chunk.metadata)
        if isinstance(chunk.content, dict):
            return deepcopy(chunk.content)
        return {"value": chunk.content}

    return chunk.content


def _extract_execution_id(payload: Any) -> Optional[str]:
    if hasattr(payload, "metadata") and isinstance(getattr(payload, "metadata", None), dict):
        metadata = getattr(payload, "metadata")
        if metadata.get("execution_id"):
            return str(metadata["execution_id"])

    if hasattr(payload, "content") and isinstance(getattr(payload, "content", None), dict):
        content = getattr(payload, "content")
        if content.get("execution_id"):
            return str(content["execution_id"])

    if isinstance(payload, dict) and payload.get("execution_id"):
        return str(payload["execution_id"])

    return None
