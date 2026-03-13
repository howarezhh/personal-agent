"""
瀵硅瘽API鎺ュ彛
鎻愪緵鐢ㄦ埛鎻愰棶鍜屾祦寮忚緭鍑哄姛鑳?
"""

import json
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


logger = get_logger(__name__)


class NonStreamChatResult(TypedDict, total=False):
    answer: str
    execution_id: Optional[str]
    assistant_message_id: Optional[str]


def get_chat_application_service() -> ChatApplicationService:
    return build_chat_application_service()

# 鍒涘缓璺敱鍣?
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class AskRequest(BaseModel):
    """鐢ㄦ埛鎻愰棶璇锋眰"""
    question: str = Field(..., min_length=1, max_length=5000, description="鐢ㄦ埛闂")
    conversation_id: Optional[str] = Field(None, description="浼氳瘽ID锛堝彲閫夛紝涓嶆彁渚涘垯鍒涘缓鏂颁細璇濓級")
    stream: bool = Field(default=True, description="鏄惁浣跨敤娴佸紡杈撳嚭")
    enable_knowledge_base: bool = Field(default=False, description="是否启用知识库增强")
    knowledge_base_id: Optional[str] = Field(default=None, description="Selected knowledge base ID")


class PauseRequest(BaseModel):
    """鏆傚仠娴佸紡瀵硅瘽璇锋眰"""
    stream_id: str = Field(..., min_length=1, description="娴佸紡浼氳瘽ID")

class PauseStreamResponse(BaseModel):
    stream_id: str = Field(..., description="???? ID")
    paused: bool = Field(..., description="?????")


active_streams: Dict[str, Dict[str, Any]] = {}
active_streams_lock = asyncio.Lock()


def _get_chat_history_limit() -> int:
    """读取会话历史上限配置，避免硬编码。"""
    config_manager = get_config_manager()
    history_config = config_manager.get("conversation_history", {}) or {}
    raw_limit = history_config.get("max_history_length", 10)
    try:
        return max(1, int(raw_limit))
    except (TypeError, ValueError):
        return 10


class AskResponse(BaseModel):
    """用户提问响应（非流式）"""
    conversation_id: str = Field(..., description="会话ID")
    message_id: str = Field(..., description="消息ID")
    answer: str = Field(..., description="助手回答")
    execution_id: Optional[str] = Field(None, description="执行ID")

@router.post("/pause", response_model=SuccessResponse[PauseStreamResponse])
async def pause_stream(
    request: PauseRequest,
    user_id: str = Depends(get_current_user_id)
):
    """暂停正在执行的流式对话。"""
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
    """用于日志中的数据结构摘要，避免输出过长内容。"""
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
    """
    鐢ㄦ埛鎻愰棶鎺ュ彛锛堜娇鐢ㄥ伐浣滄祦鎵ц鍣級

    瀹屾暣澶勭悊娴佺▼锛?
    1. 楠岃瘉鐢ㄦ埛韬唤锛堜娇鐢╣et_current_user_id渚濊禆锛?
    2. 鍒涘缓鎴栬幏鍙栦細璇?
    3. 淇濆瓨鐢ㄦ埛娑堟伅鍒版暟鎹簱
    4. 浣跨敤WorkflowExecutor鎵ц宸ヤ綔娴?
    5. 娴佸紡杩斿洖鐢熸垚鍐呭锛堜娇鐢⊿treamingResponse锛?
    6. 淇濆瓨鍔╂墜鍥炲鍒版暟鎹簱
    7. 淇濆瓨鏅鸿兘浣撴墽琛岃褰?

    Args:
        request: 鎻愰棶璇锋眰
        user_id: 褰撳墠鐢ㄦ埛ID锛堜粠token鑾峰彇锛?

    Returns:
        娴佸紡鍝嶅簲鎴栨櫘閫氬搷搴?

    Raises:
        HTTPException: 处理失败
    """
    try:
        logger.info(f"[CHAT] 收到用户提问: user_id={user_id}, question={request.question[:50]}...")
        logger.info(f"[CHAT] request params: conversation_id={request.conversation_id}, stream={request.stream}, enable_knowledge_base={request.enable_knowledge_base}, knowledge_base_id={request.knowledge_base_id}")
        app_service = get_chat_application_service()

        # 1. 鍒涘缓鎴栬幏鍙栦細璇?
        conversation, conversation_id = app_service.ensure_conversation(
            user_id=user_id,
            conversation_id=request.conversation_id,
            question=request.question,
        )
        if not conversation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在或访问被拒绝")

        # 2. 鑾峰彇瀵硅瘽鍘嗗彶锛堝湪淇濆瓨鐢ㄦ埛娑堟伅涔嬪墠鑾峰彇锛岄伩鍏嶅寘鍚綋鍓嶆秷鎭級
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

        # 3. 淇濆瓨鐢ㄦ埛娑堟伅鍒版暟鎹簱
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

        # 4. 鏍规嵁鏄惁娴佸紡杩斿洖涓嶅悓鍝嶅簲
        if request.stream:
            logger.info("[CHAT] 使用流式响应")
            # 娴佸紡鍝嶅簲
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
            # 闈炴祦寮忓搷搴?
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
    """
    娴佸紡鍝嶅簲鐢熸垚鍣紙浣跨敤宸ヤ綔娴佹墽琛屽櫒锛?

    Args:
        user_id: 鐢ㄦ埛ID
        conversation_id: 浼氳瘽ID
        user_message_id: 鐢ㄦ埛娑堟伅ID
        question: 鐢ㄦ埛闂
        conversation_history: 瀵硅瘽鍘嗗彶

    Yields:
        SSE鏍煎紡鐨勬暟鎹潡
    """
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

        # 浣跨敤宸ヤ綔娴佹墽琛屽櫒
        logger.info("[CHAT-STREAM] 创建工作流执行器")
        logger.info("[CHAT-STREAM] 工作流执行器创建成功")

        full_answer = ""
        citations = []
        execution_id = None
        assistant_message_id = None

        # 鎵ц宸ヤ綔娴?
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

        # 保存助手回复
        if full_answer:
            logger.info("[CHAT-STREAM] 保存助手回复")
            assistant_message = app_service.save_assistant_message(
                conversation_id=conversation_id,
                content=full_answer,
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
            logger.debug("[CHAT-STREAM] 浼氳瘽鏃堕棿鎴冲凡鏇存柊")

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
    """生成非流式回答并持久化助手消息。"""
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

        if full_answer:
            assistant_message = app_service.save_assistant_message(
                conversation_id=conversation_id,
                content=full_answer,
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
            "answer": full_answer,
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
    """
    鏍煎紡鍖朣SE鏁版嵁

    Args:
        event_type: 浜嬩欢绫诲瀷
        data: 鏁版嵁鍐呭

    Returns:
        鏍煎紡鍖栧悗鐨凷SE瀛楃涓?
    """
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
    """灏哠treamChunk 杞崲涓哄墠绔洿绋冲畾鐨勪簨浠惰浇鑽枫€?"""
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
