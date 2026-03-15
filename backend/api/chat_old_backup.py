
import json
import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from backend.api.dependencies import get_current_user_id
from backend.api.models import SuccessResponse, ErrorResponse
from backend.database.repositories.conversation_repository import get_conversation_repository
from backend.database.repositories.message_repository import get_message_repository
from backend.database.repositories.agent_execution_repository import get_agent_execution_repository
from backend.models.conversation import ConversationCreate
from backend.models.message import MessageCreate, MessageType
from backend.agents.router.router_agent import RouterAgent
from backend.agents.generation.generation_agent import GenerationAgent
from backend.agents.retrieval.retrieval_agent import RetrievalAgent
from backend.agents.tool.tool_agent import ToolAgent
from backend.agents.base.agent_input import AgentInput
from backend.utils.logger import get_logger


logger = get_logger(__name__)

# 创建路由器
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=5000, description="用户问题")
    conversation_id: Optional[str] = Field(None, description="会话ID（可选，不提供则创建新会话）")
    stream: bool = Field(default=True, description="是否使用流式输出")


class AskResponse(BaseModel):
    conversation_id: str = Field(..., description="会话ID")
    message_id: str = Field(..., description="消息ID")
    answer: str = Field(..., description="助手回答")
    execution_id: Optional[str] = Field(None, description="执行ID")


@router.post("/ask")
async def ask(
    request: AskRequest,
    user_id: str = Depends(get_current_user_id)
):
    try:
        logger.info(f"[CHAT] 收到用户提问: user_id={user_id}, question={request.question[:50]}...")
        logger.info(f"[CHAT] 请求参数: conversation_id={request.conversation_id}, stream={request.stream}")

        # 获取仓储实例
        logger.debug("[CHAT] 获取仓储实例")
        conversation_repo = get_conversation_repository()
        message_repo = get_message_repository()
        logger.debug("[CHAT] 仓储实例获取成功")

        # 1. 创建或获取会话
        if request.conversation_id:
            logger.info(f"[CHAT] 使用现有会话: {request.conversation_id}")
            # 验证会话是否存在且属于当前用户
            conversation = conversation_repo.get_conversation_with_user_check(
                conversation_id=request.conversation_id,
                user_id=user_id
            )
            if not conversation:
                logger.warning(f"[CHAT] 会话不存在或无权访问: {request.conversation_id}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="会话不存在或访问被拒绝"
                )
            conversation_id = request.conversation_id
            logger.info(f"[CHAT] 会话验证成功: {conversation_id}")
        else:
            logger.info("[CHAT] 创建新会话")
            # 创建新会话
            conversation_create = ConversationCreate(
                user_id=user_id,
                title=request.question[:50] + ("..." if len(request.question) > 50 else "")
            )
            conversation = conversation_repo.create_conversation(conversation_create)
            conversation_id = conversation.conversation_id
            logger.info(f"[CHAT] 新会话创建成功: {conversation_id}")

        # 2. 获取对话历史（在保存用户消息之前获取，避免包含当前消息）
        logger.debug("[CHAT] 获取对话历史")
        conversation_history = message_repo.get_conversation_history(
            conversation_id=conversation_id,
            limit=10
        )
        logger.debug(f"[CHAT] 获取到{len(conversation_history)}条历史消息")

        # 格式化对话历史
        history_list = [
            {
                "role": "user" if msg.message_type == "user" else "assistant",
                "content": msg.content
            }
            for msg in conversation_history
        ]

        # 3. 保存用户消息到数据库
        logger.info("[CHAT] 保存用户消息")
        user_message_seq = message_repo.get_next_sequence_number(conversation_id)
        logger.debug(f"[CHAT] 用户消息序号: {user_message_seq}")

        user_message_create = MessageCreate(
            conversation_id=conversation_id,
            message_type="user",
            content=request.question,
            sequence_number=user_message_seq
        )
        user_message = message_repo.create_message(user_message_create)
        logger.info(f"[CHAT] 用户消息保存成功: message_id={user_message.message_id}")

        # 4. 根据是否流式返回不同响应
        if request.stream:
            logger.info("[CHAT] 使用流式响应")
            # 流式响应
            return StreamingResponse(
                _stream_response(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    user_message_id=user_message.message_id,
                    question=request.question,
                    conversation_history=history_list
                ),
                media_type="text/event-stream"
            )
        else:
            logger.info("[CHAT] 使用非流式响应")
            # 非流式响应
            answer = await _non_stream_response(
                user_id=user_id,
                conversation_id=conversation_id,
                user_message_id=user_message.message_id,
                question=request.question,
                conversation_history=history_list
            )

            return SuccessResponse.create(
                data=AskResponse(
                    conversation_id=conversation_id,
                    message_id=user_message.message_id,
                    answer=answer
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


async def _stream_response(
    user_id: str,
    conversation_id: str,
    user_message_id: str,
    question: str,
    conversation_history: list
):
    try:
        logger.info("[CHAT-STREAM] ========== 开始流式响应生成 ==========")
        logger.info(f"[CHAT-STREAM] 用户ID: {user_id}")
        logger.info(f"[CHAT-STREAM] 会话ID: {conversation_id}")
        logger.info(f"[CHAT-STREAM] 消息ID: {user_message_id}")
        logger.info(f"[CHAT-STREAM] 问题: {question[:100]}...")
        logger.info(f"[CHAT-STREAM] 历史消息数量: {len(conversation_history)}")

        logger.debug("[CHAT-STREAM] 获取仓储实例")
        message_repo = get_message_repository()
        conversation_repo = get_conversation_repository()
        logger.debug("[CHAT-STREAM] 仓储实例获取成功")

        # 创建智能体实例
        logger.info("[CHAT-STREAM] 创建智能体实例")
        router_agent = RouterAgent()
        generation_agent = GenerationAgent()
        retrieval_agent = RetrievalAgent()
        tool_agent = ToolAgent()
        logger.info("[CHAT-STREAM] 智能体实例创建成功")

        # 构建智能体输入
        logger.debug("[CHAT-STREAM] 构建智能体输入")
        agent_input = AgentInput(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=user_message_id,
            content=question,
            metadata={"conversation_history": conversation_history}
        )
        logger.debug("[CHAT-STREAM] 智能体输入构建完成")

        # 1. 调用路由Agent分析问题
        logger.info("[CHAT-STREAM] ========== 步骤1: 调用路由Agent ==========")
        logger.info("[CHAT-STREAM] 发送thinking事件: 正在分析问题类型...")
        yield _format_sse_data("thinking", "正在分析问题类型...")

        logger.info("[CHAT-STREAM] 开始执行router_agent.execute()")
        router_output = await router_agent.execute(agent_input)
        logger.info(f"[CHAT-STREAM] router_agent.execute()执行完成，成功: {router_output.is_success()}")

        if not router_output.is_success():
            error_msg = router_output.error_message or "路由分析失败"
            logger.error(f"[CHAT-STREAM] 路由Agent执行失败: {error_msg}")
            logger.info("[CHAT-STREAM] 发送error事件")
            yield _format_sse_data("error", error_msg)
            logger.info("[CHAT-STREAM] ========== 流式响应结束（路由失败） ==========")
            return

        # 获取路由决策
        decision = router_output.metadata.get("decision", {})
        action = decision.get("action", "direct_answer")
        logger.info(f"[CHAT-STREAM] 路由决策: action={action}")
        logger.info(f"[CHAT-STREAM] 路由决策详情: {decision}")

        # 2. 根据路由决策调用相应的Agent
        logger.info("[CHAT-STREAM] ========== 步骤2: 根据路由决策执行Agent ==========")
        full_answer = ""
        citations = []

        if action == "retrieval":
            logger.info("[CHAT-STREAM] 执行检索增强生成流程")
            # 检索增强生成流程
            logger.info("[CHAT-STREAM] 发送thinking事件: 正在检索知识库...")
            yield _format_sse_data("thinking", "正在检索知识库...")

            # 调用检索Agent
            logger.info("[CHAT-STREAM] 开始调用retrieval_agent.execute_stream()")
            retrieval_results = []
            chunk_count = 0
            async for chunk in retrieval_agent.execute_stream(agent_input):
                chunk_count += 1
                logger.debug(f"[CHAT-STREAM] 检索Agent返回chunk #{chunk_count}: type={chunk.chunk_type}")
                if chunk.chunk_type == "thinking":
                    logger.info(f"[CHAT-STREAM] 检索thinking: {chunk.content}")
                    yield _format_sse_data("thinking", chunk.content)
                elif chunk.chunk_type == "error":
                    logger.error(f"[CHAT-STREAM] 检索错误: {chunk.content}")
                    yield _format_sse_data("error", chunk.content)
                    return
                elif chunk.chunk_type == "result":
                    # 获取检索结果
                    retrieval_results = chunk.content.get("retrieval_results", [])
                    total_results = chunk.content.get("total_results", 0)
                    logger.info(f"[CHAT-STREAM] 检索完成: 找到{total_results}条结果")
                    yield _format_sse_data("thinking", f"找到{total_results}条相关结果")

            logger.info(f"[CHAT-STREAM] 检索Agent执行完成，共接收{chunk_count}个chunk")

            # 检查是否有检索结果
            if not retrieval_results:
                logger.warning("[CHAT-STREAM] 未找到检索结果，降级为直接回答")
                logger.info("[CHAT-STREAM] 发送thinking事件: 未找到相关信息，使用通用知识回答...")
                yield _format_sse_data("thinking", "未找到相关信息，使用通用知识回答...")
                # 降级为直接回答
                logger.info("[CHAT-STREAM] 开始调用generation_agent.execute_stream()")
                gen_chunk_count = 0
                async for chunk in generation_agent.execute_stream(agent_input):
                    gen_chunk_count += 1
                    logger.debug(f"[CHAT-STREAM] 生成Agent返回chunk #{gen_chunk_count}: type={chunk.chunk_type}")
                    if chunk.chunk_type == "thinking":
                        logger.info(f"[CHAT-STREAM] 生成thinking: {chunk.content}")
                        yield _format_sse_data("thinking", chunk.content)
                    elif chunk.chunk_type == "content":
                        logger.debug(f"[CHAT-STREAM] 生成content片段: {len(chunk.content)}字符")
                        full_answer += chunk.content
                        yield _format_sse_data("content", chunk.content)
                    elif chunk.chunk_type == "error":
                        logger.error(f"[CHAT-STREAM] 生成错误: {chunk.content}")
                        yield _format_sse_data("error", chunk.content)
                        return
                logger.info(f"[CHAT-STREAM] 生成Agent执行完成，共接收{gen_chunk_count}个chunk，生成{len(full_answer)}字符")
            else:
                # 基于检索结果生成回答
                logger.info("[CHAT-STREAM] 基于检索结果生成回答")
                logger.info("[CHAT-STREAM] 发送thinking事件: 正在生成回答...")
                yield _format_sse_data("thinking", "正在生成回答...")

                logger.info("[CHAT-STREAM] 开始调用generation_agent.generate_with_context_stream()")
                gen_chunk_count = 0
                async for chunk in generation_agent.generate_with_context_stream(agent_input, retrieval_results):
                    gen_chunk_count += 1
                    logger.debug(f"[CHAT-STREAM] 生成Agent返回chunk #{gen_chunk_count}: type={chunk.chunk_type}")
                    if chunk.chunk_type == "thinking":
                        logger.info(f"[CHAT-STREAM] 生成thinking: {chunk.content}")
                        yield _format_sse_data("thinking", chunk.content)
                    elif chunk.chunk_type == "content":
                        logger.debug(f"[CHAT-STREAM] 生成content片段: {len(chunk.content)}字符")
                        full_answer += chunk.content
                        yield _format_sse_data("content", chunk.content)
                    elif chunk.chunk_type == "error":
                        logger.error(f"[CHAT-STREAM] 生成错误: {chunk.content}")
                        yield _format_sse_data("error", chunk.content)
                        return
                    elif chunk.chunk_type == "result":
                        # 获取引用信息
                        citations = chunk.content.get("citations", [])
                        logger.info(f"[CHAT-STREAM] 获取到{len(citations)}条引用")
                logger.info(f"[CHAT-STREAM] 生成Agent执行完成，共接收{gen_chunk_count}个chunk，生成{len(full_answer)}字符")

        elif action == "direct_answer":
            logger.info("[CHAT-STREAM] 执行直接回答流程")
            # 直接回答
            logger.info("[CHAT-STREAM] 发送thinking事件: 正在生成回答...")
            yield _format_sse_data("thinking", "正在生成回答...")

            # 流式调用生成Agent
            logger.info("[CHAT-STREAM] 开始调用generation_agent.execute_stream()")
            gen_chunk_count = 0
            async for chunk in generation_agent.execute_stream(agent_input):
                gen_chunk_count += 1
                logger.debug(f"[CHAT-STREAM] 生成Agent返回chunk #{gen_chunk_count}: type={chunk.chunk_type}")
                if chunk.chunk_type == "thinking":
                    logger.info(f"[CHAT-STREAM] 生成thinking: {chunk.content}")
                    yield _format_sse_data("thinking", chunk.content)
                elif chunk.chunk_type == "content":
                    logger.debug(f"[CHAT-STREAM] 生成content片段: {len(chunk.content)}字符")
                    full_answer += chunk.content
                    yield _format_sse_data("content", chunk.content)
                elif chunk.chunk_type == "error":
                    logger.error(f"[CHAT-STREAM] 生成错误: {chunk.content}")
                    yield _format_sse_data("error", chunk.content)
                    return
                elif chunk.chunk_type == "result":
                    # 完成
                    logger.debug("[CHAT-STREAM] 生成Agent返回result")
                    pass
            logger.info(f"[CHAT-STREAM] 生成Agent执行完成，共接收{gen_chunk_count}个chunk，生成{len(full_answer)}字符")

        elif action == "tool_call":
            logger.info("[CHAT-STREAM] 执行工具调用流程")
            # 工具调用流程
            logger.info("[CHAT-STREAM] 发送thinking事件: 正在选择合适的工具...")
            yield _format_sse_data("thinking", "正在选择合适的工具...")

            # 调用工具Agent
            logger.info("[CHAT-STREAM] 开始调用tool_agent.execute_stream()")
            tool_result = None
            tool_chunk_count = 0
            async for chunk in tool_agent.execute_stream(agent_input):
                tool_chunk_count += 1
                logger.debug(f"[CHAT-STREAM] 工具Agent返回chunk #{tool_chunk_count}: type={chunk.chunk_type}")
                if chunk.chunk_type == "thinking":
                    logger.info(f"[CHAT-STREAM] 工具thinking: {chunk.content}")
                    yield _format_sse_data("thinking", chunk.content)
                elif chunk.chunk_type == "tool_call":
                    # 发送工具调用信息
                    tool_info = chunk.content
                    tool_name = tool_info.get("tool_name", "")
                    tool_status = tool_info.get("status", "")
                    logger.info(f"[CHAT-STREAM] 工具调用: tool_name={tool_name}, status={tool_status}")

                    if tool_status == "starting":
                        yield _format_sse_data("tool_call", json.dumps({
                            "tool_name": tool_name,
                            "status": "starting"
                        }))
                    elif tool_status == "completed":
                        yield _format_sse_data("tool_call", json.dumps({
                            "tool_name": tool_name,
                            "status": "completed",
                            "execution_time_ms": tool_info.get("execution_time_ms", 0)
                        }))
                elif chunk.chunk_type == "error":
                    logger.error(f"[CHAT-STREAM] 工具错误: {chunk.content}")
                    yield _format_sse_data("error", chunk.content)
                    return
                elif chunk.chunk_type == "result":
                    # 获取工具调用结果
                    tool_result = chunk.content
                    logger.info(f"[CHAT-STREAM] 工具调用结果: {tool_result}")

            logger.info(f"[CHAT-STREAM] 工具Agent执行完成，共接收{tool_chunk_count}个chunk")

            # 检查工具调用是否成功
            if tool_result and not tool_result.get("no_tool_needed", False):
                logger.info("[CHAT-STREAM] 基于工具结果生成回答")
                # 基于工具结果生成回答
                logger.info("[CHAT-STREAM] 发送thinking事件: 正在基于工具结果生成回答...")
                yield _format_sse_data("thinking", "正在基于工具结果生成回答...")

                logger.info("[CHAT-STREAM] 开始调用generation_agent.generate_with_tool_result_stream()")
                gen_chunk_count = 0
                async for chunk in generation_agent.generate_with_tool_result_stream(agent_input, tool_result):
                    gen_chunk_count += 1
                    logger.debug(f"[CHAT-STREAM] 生成Agent返回chunk #{gen_chunk_count}: type={chunk.chunk_type}")
                    if chunk.chunk_type == "thinking":
                        logger.info(f"[CHAT-STREAM] 生成thinking: {chunk.content}")
                        yield _format_sse_data("thinking", chunk.content)
                    elif chunk.chunk_type == "content":
                        logger.debug(f"[CHAT-STREAM] 生成content片段: {len(chunk.content)}字符")
                        full_answer += chunk.content
                        yield _format_sse_data("content", chunk.content)
                    elif chunk.chunk_type == "error":
                        logger.error(f"[CHAT-STREAM] 生成错误: {chunk.content}")
                        yield _format_sse_data("error", chunk.content)
                        return
                    elif chunk.chunk_type == "result":
                        # 完成
                        logger.debug("[CHAT-STREAM] 生成Agent返回result")
                        pass
                logger.info(f"[CHAT-STREAM] 生成Agent执行完成，共接收{gen_chunk_count}个chunk，生成{len(full_answer)}字符")
            else:
                logger.warning("[CHAT-STREAM] 不需要工具或工具调用失败，降级为直接回答")
                # 不需要工具或工具调用失败，降级为直接回答
                logger.info("[CHAT-STREAM] 发送thinking事件: 正在生成回答...")
                yield _format_sse_data("thinking", "正在生成回答...")

                logger.info("[CHAT-STREAM] 开始调用generation_agent.execute_stream()")
                gen_chunk_count = 0
                async for chunk in generation_agent.execute_stream(agent_input):
                    gen_chunk_count += 1
                    logger.debug(f"[CHAT-STREAM] 生成Agent返回chunk #{gen_chunk_count}: type={chunk.chunk_type}")
                    if chunk.chunk_type == "thinking":
                        logger.info(f"[CHAT-STREAM] 生成thinking: {chunk.content}")
                        yield _format_sse_data("thinking", chunk.content)
                    elif chunk.chunk_type == "content":
                        logger.debug(f"[CHAT-STREAM] 生成content片段: {len(chunk.content)}字符")
                        full_answer += chunk.content
                        yield _format_sse_data("content", chunk.content)
                    elif chunk.chunk_type == "error":
                        logger.error(f"[CHAT-STREAM] 生成错误: {chunk.content}")
                        yield _format_sse_data("error", chunk.content)
                        return
                    elif chunk.chunk_type == "result":
                        # 完成
                        logger.debug("[CHAT-STREAM] 生成Agent返回result")
                        pass
                logger.info(f"[CHAT-STREAM] 生成Agent执行完成，共接收{gen_chunk_count}个chunk，生成{len(full_answer)}字符")

        else:
            # 其他类型暂不支持
            error_msg = f"Action type '{action}' not supported yet"
            logger.warning(f"[CHAT-STREAM] {error_msg}")
            yield _format_sse_data("error", error_msg)
            logger.info("[CHAT-STREAM] ========== 流式响应结束（不支持的action类型） ==========")
            return

        # 3. 保存助手回复到数据库
        logger.info("[CHAT-STREAM] ========== 步骤3: 保存助手回复到数据库 ==========")
        if full_answer:
            logger.info(f"[CHAT-STREAM] 保存助手回复，长度: {len(full_answer)}字符")
            assistant_message_seq = message_repo.get_next_sequence_number(conversation_id)
            logger.debug(f"[CHAT-STREAM] 助手消息序号: {assistant_message_seq}")
            assistant_message_create = MessageCreate(
                conversation_id=conversation_id,
                message_type="assistant",
                content=full_answer,
                sequence_number=assistant_message_seq,
                parent_message_id=user_message_id
            )
            assistant_message = message_repo.create_message(assistant_message_create)
            logger.info(f"[CHAT-STREAM] 助手消息保存成功: message_id={assistant_message.message_id}")

            # 更新会话消息计数（用户消息+助手消息=2条）
            logger.info(f"[CHAT-STREAM] 更新会话消息计数: conversation_id={conversation_id}")
            conversation_repo.update_message_count(conversation_id, increment=2)
            logger.info(f"[CHAT-STREAM] 会话消息计数更新成功")

            # 发送完成信号（包含引用信息）
            done_data = {
                "conversation_id": conversation_id,
                "message_id": assistant_message.message_id,
                "content_length": len(full_answer),
                "citations": citations
            }
            logger.info(f"[CHAT-STREAM] 发送done事件: {done_data}")
            yield _format_sse_data("done", json.dumps(done_data))
        else:
            logger.warning(f"[CHAT-STREAM] 没有生成回答，但仍更新会话时间戳")
            # 即使没有生成回答，也更新会话时间戳
            conversation_repo.update_conversation_timestamp(conversation_id)
            done_data = {
                "conversation_id": conversation_id,
                "message_id": user_message_id,
                "content_length": 0,
                "citations": []
            }
            logger.info(f"[CHAT-STREAM] 发送done事件: {done_data}")
            yield _format_sse_data("done", json.dumps(done_data))

        logger.info("[CHAT-STREAM] ========== 流式响应生成完成 ==========")

    except Exception as e:
        logger.error(f"[CHAT-STREAM] 流式响应失败: {str(e)}", exc_info=True)
        yield _format_sse_data("error", str(e))


async def _non_stream_response(
    user_id: str,
    conversation_id: str,
    user_message_id: str,
    question: str,
    conversation_history: list
) -> str:
    try:
        message_repo = get_message_repository()
        conversation_repo = get_conversation_repository()

        # 创建智能体实例
        router_agent = RouterAgent()
        generation_agent = GenerationAgent()
        retrieval_agent = RetrievalAgent()
        tool_agent = ToolAgent()

        # 构建智能体输入
        agent_input = AgentInput(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=user_message_id,
            content=question,
            metadata={"conversation_history": conversation_history}
        )

        # 1. 调用路由Agent分析问题
        logger.info("Calling router agent...")
        router_output = await router_agent.execute(agent_input)

        if not router_output.is_success():
            error_msg = router_output.error_message or "路由分析失败"
            logger.error(f"Router agent failed: {error_msg}")
            raise Exception(error_msg)

        # 获取路由决策
        decision = router_output.metadata.get("decision", {})
        action = decision.get("action", "direct_answer")
        logger.info(f"Router decision: {action}")

        # 2. 根据路由决策调用相应的Agent
        answer = ""

        if action == "retrieval":
            # 检索增强生成流程
            logger.info("Calling retrieval agent...")
            retrieval_output = await retrieval_agent.execute(agent_input)

            if not retrieval_output.is_success():
                logger.warning("Retrieval failed, falling back to direct answer")
                # 降级为直接回答
                generation_output = await generation_agent.execute(agent_input)
                if not generation_output.is_success():
                    error_msg = generation_output.error_message or "生成回答失败"
                    logger.error(f"Generation agent failed: {error_msg}")
                    raise Exception(error_msg)
                answer = generation_output.content
            else:
                # 获取检索结果
                retrieval_results = retrieval_output.metadata.get("retrieval_results", [])

                if not retrieval_results:
                    logger.warning("No retrieval results found, falling back to direct answer")
                    # 降级为直接回答
                    generation_output = await generation_agent.execute(agent_input)
                    if not generation_output.is_success():
                        error_msg = generation_output.error_message or "生成回答失败"
                        logger.error(f"Generation agent failed: {error_msg}")
                        raise Exception(error_msg)
                    answer = generation_output.content
                else:
                    # 基于检索结果生成回答
                    logger.info("Calling generation agent with context...")
                    generation_output = await generation_agent.generate_with_context(agent_input, retrieval_results)

                    if not generation_output.is_success():
                        error_msg = generation_output.error_message or "生成回答失败"
                        logger.error(f"Generation agent failed: {error_msg}")
                        raise Exception(error_msg)

                    answer = generation_output.content

        elif action == "direct_answer":
            # 直接回答
            logger.info("Calling generation agent...")
            generation_output = await generation_agent.execute(agent_input)

            if not generation_output.is_success():
                error_msg = generation_output.error_message or "生成回答失败"
                logger.error(f"Generation agent failed: {error_msg}")
                raise Exception(error_msg)

            answer = generation_output.content

        elif action == "tool_call":
            # 工具调用流程
            logger.info("Calling tool agent...")
            tool_output = await tool_agent.execute(agent_input)

            if not tool_output.is_success():
                logger.warning("Tool call failed, falling back to direct answer")
                # 降级为直接回答
                generation_output = await generation_agent.execute(agent_input)
                if not generation_output.is_success():
                    error_msg = generation_output.error_message or "生成回答失败"
                    logger.error(f"Generation agent failed: {error_msg}")
                    raise Exception(error_msg)
                answer = generation_output.content
            else:
                # 检查是否需要工具
                if tool_output.metadata.get("no_tool_needed", False):
                    logger.info("No tool needed, using direct answer")
                    generation_output = await generation_agent.execute(agent_input)
                    if not generation_output.is_success():
                        error_msg = generation_output.error_message or "生成回答失败"
                        logger.error(f"Generation agent failed: {error_msg}")
                        raise Exception(error_msg)
                    answer = generation_output.content
                else:
                    # 基于工具结果生成回答
                    tool_result = {
                        "tool_name": tool_output.metadata.get("tool_name"),
                        "tool_params": tool_output.metadata.get("tool_params"),
                        "tool_result": tool_output.metadata.get("tool_result"),
                        "interpreted_result": tool_output.metadata.get("interpreted_result"),
                        "execution_time_ms": tool_output.metadata.get("execution_time_ms")
                    }

                    logger.info("Calling generation agent with tool result...")
                    generation_output = await generation_agent.generate_with_tool_result(agent_input, tool_result)

                    if not generation_output.is_success():
                        error_msg = generation_output.error_message or "生成回答失败"
                        logger.error(f"Generation agent failed: {error_msg}")
                        raise Exception(error_msg)

                    answer = generation_output.content

        else:
            # 其他类型暂不支持
            error_msg = f"Action type '{action}' not supported yet"
            logger.warning(error_msg)
            raise Exception(error_msg)

        # 3. 保存助手回复到数据库
        if answer:
            assistant_message_seq = message_repo.get_next_sequence_number(conversation_id)
            assistant_message_create = MessageCreate(
                conversation_id=conversation_id,
                message_type="assistant",
                content=answer,
                sequence_number=assistant_message_seq,
                parent_message_id=user_message_id
            )
            assistant_message = message_repo.create_message(assistant_message_create)
            logger.info(f"Assistant message saved: message_id={assistant_message.message_id}")

            # 更新会话消息计数
            conversation_repo.update_message_count(conversation_id, increment=2)

        return answer

    except Exception as e:
        logger.error(f"Non-stream response failed: {str(e)}", exc_info=True)
        raise


def _format_sse_data(event_type: str, data: str) -> str:
    import datetime

    event_data = {
        "type": event_type,
        "content": data,
        "timestamp": datetime.datetime.utcnow().isoformat()
    }

    return f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"


# ==================== 使用工作流执行器的新端点 ====================

@router.post("/ask-v2")
async def ask_v2(
    request: AskRequest,
    user_id: str = Depends(get_current_user_id)
):
    try:
        from backend.workflows.workflow_executor import WorkflowExecutor
        
        conversation_repo = get_conversation_repository()
        message_repo = get_message_repository()
        
        # 1. 获取或创建会话
        conversation_id = request.conversation_id
        if not conversation_id:
            # 创建新会话
            conversation_create = ConversationCreate(
                user_id=user_id,
                title=request.question[:50]  # 使用问题前50个字符作为标题
            )
            conversation = conversation_repo.create_conversation(conversation_create)
            conversation_id = conversation.conversation_id
            logger.info(f"创建新会话: {conversation_id}")
        else:
            # 验证会话是否存在且属于当前用户
            conversation = conversation_repo.get_conversation_by_id(conversation_id)
            if not conversation:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="会话不存在"
                )
            if conversation.user_id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="您没有权限访问此会话"
                )
        
        # 2. 保存用户消息
        user_message_create = MessageCreate(
            conversation_id=conversation_id,
            message_type="user",
            content=request.question
        )
        user_message = message_repo.create_message(user_message_create)
        logger.info(f"保存用户消息: {user_message.message_id}")

        # 3. 获取对话历史
        history_messages = message_repo.get_messages_by_conversation(
            conversation_id,
            limit=10
        )
        history_list = [
            {
                "role": "user" if msg.message_type == "user" else "assistant",
                "content": msg.content
            }
            for msg in history_messages[:-1]  # 排除刚保存的用户消息
        ]
        
        # 4. 使用工作流执行器处理请求
        if request.stream:
            # 流式响应
            return StreamingResponse(
                _stream_response_v2(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    user_message_id=user_message.message_id,
                    question=request.question,
                    conversation_history=history_list
                ),
                media_type="text/event-stream"
            )
        else:
            # 非流式响应（暂不支持）
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="V2 API不支持非流式模式"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ask V2接口失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"处理问题失败: {str(e)}"
        )


async def _stream_response_v2(
    user_id: str,
    conversation_id: str,
    user_message_id: str,
    question: str,
    conversation_history: list
):
    try:
        from backend.workflows.workflow_executor import WorkflowExecutor
        
        message_repo = get_message_repository()
        conversation_repo = get_conversation_repository()
        
        # 构建智能体输入
        agent_input = AgentInput(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=user_message_id,
            content=question,
            metadata={"conversation_history": conversation_history}
        )
        
        # 使用工作流执行器
        workflow_executor = WorkflowExecutor()
        
        full_answer = ""
        citations = []
        
        # 执行工作流
        async for chunk in workflow_executor.execute_workflow(agent_input):
            if chunk.chunk_type == "thinking":
                yield _format_sse_data("thinking", chunk.content)
            
            elif chunk.chunk_type == "content":
                full_answer += chunk.content
                yield _format_sse_data("content", chunk.content)
            
            elif chunk.chunk_type == "tool_call":
                yield _format_sse_data("tool_call", chunk.content)
            
            elif chunk.chunk_type == "result":
                # 获取引用信息（如果有）
                if "citations" in chunk.content:
                    citations = chunk.content.get("citations", [])
            
            elif chunk.chunk_type == "error":
                yield _format_sse_data("error", chunk.content)
                return
        
        # 保存助手回复
        if full_answer:
            assistant_message_create = MessageCreate(
                conversation_id=conversation_id,
                message_type="assistant",
                content=full_answer,
                metadata={"citations": citations} if citations else None
            )
            assistant_message = message_repo.create_message(assistant_message_create)
            logger.info(f"保存助手消息: {assistant_message.message_id}")
            
            # 更新会话的最后活动时间
            conversation_repo.update_conversation_timestamp(conversation_id)
        
        # 发送完成信号
        yield _format_sse_data("done", {
            "conversation_id": conversation_id,
            "citations": citations
        })
    
    except Exception as e:
        logger.error(f"流式响应V2失败: {str(e)}", exc_info=True)
        yield _format_sse_data("error", f"生成回答失败: {str(e)}")
