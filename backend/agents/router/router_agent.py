# -*- coding: utf-8 -*-

import time
import json
"""
路由 Agent 模块，负责组织模型消息并产出路由决策结果。
"""

from typing import AsyncGenerator

from pydantic import BaseModel

from pydantic import BaseModel

from backend.agents.base.base_agent import BaseAgent
from backend.agents.base.agent_input import AgentInput
from backend.agents.base.agent_output import AgentOutput
from backend.agents.base.stream_chunk import StreamChunk
from backend.core.llm_manager import get_langchain_model_manager
from backend.database.repositories.agent_execution_repository import get_agent_execution_repository
from backend.models.agent_execution import AgentExecutionCreate, AgentExecutionUpdate
from backend.agents.router.decision_maker import DecisionMaker


class RouterDecisionStructuredResult(BaseModel):
    """Router decision agent."""

    action: str
    confidence: float = 0.0
    reasoning: str = ""
    should_use_tools: bool = False
    should_retrieve: bool = False
    response_style: str | None = None


class RouterAgent(BaseAgent):
    """路由 Agent，负责协调 LLM 判断与规则决策并输出最终路由结果。"""
    def __init__(self):
        """初始化路由 Agent 所需的依赖、决策器和配置。"""
        super().__init__(
            agent_name="router_agent",
            agent_type="router"
        )

        # 获取统一模型管理器。
        # model_manager: 用于保存模型调用相关的类内状态。
        self.model_manager = get_langchain_model_manager()

        # 获取执行记录仓储
        # execution_repo: 用于保存“executionrepo”相关的类内状态。
        self.execution_repo = get_agent_execution_repository()

        # 初始化决策制定器（增强版，支持工具感知和LLM协作）
        # decision_maker: 用于保存“决策maker”相关的类内状态。
        self.decision_maker = DecisionMaker()

        # 获取配置
        # confidence_threshold: 用于保存“confidencethreshold”相关的类内状态。
        self.confidence_threshold = self._get_config_value("confidence_threshold", 0.7)
        # decision_types: 用于保存“决策types”相关的类内状态。
        self.decision_types = self._get_config_value("decision_types", [
            "direct_answer", "retrieval", "tool_call", "multi_agent"
        ])

        self.logger.info("Router agent initialized")

    async def execute(self, agent_input: AgentInput) -> AgentOutput:
        """执行非流式路由流程并返回标准输出。"""
        start_time = time.time()

        try:
            self.logger.info("[ROUTER] ========== 开始路由分析 ==========")
            self.logger.info(f"[ROUTER] 会话ID: {agent_input.conversation_id}")
            self.logger.info(f"[ROUTER] 消息ID: {agent_input.message_id}")
            self.logger.info(f"[ROUTER] 用户问题: {agent_input.content[:100]}...")

            # 创建执行记录
            self.logger.debug("[ROUTER] 创建执行记录")
            execution_create = AgentExecutionCreate(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content}
            )
            execution = self.execution_repo.create_execution(execution_create)
            self.logger.debug(f"[ROUTER] 执行记录创建成功: execution_id={execution.execution_id}")

            # 获取对话历史
            conversation_history = agent_input.get_conversation_history()
            self.logger.debug(f"[ROUTER] 历史消息数量: {len(conversation_history)}")

            # 构建消息
            self.logger.debug("[ROUTER] 构建LLM消息")
            messages = self._build_messages(
                user_content=agent_input.content,
                conversation_history=conversation_history
            )
            self.logger.debug(f"[ROUTER] 构建完成，消息数量: {len(messages)}")

            # 调用LLM
            self.logger.info("[ROUTER] 调用LLM进行路由分析")
            temperature = self._get_config_value("temperature", 0.3)
            max_tokens = self._get_config_value("max_tokens", 500)
            self.logger.debug(f"[ROUTER] LLM参数: temperature={temperature}, max_tokens={max_tokens}")

            decision_model = await self.model_manager.with_structured_output(
                RouterDecisionStructuredResult
            ).invoke_messages(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            llm_decision = decision_model.model_dump()
            self.logger.info(f"[ROUTER] LLM decision result: action={llm_decision.get('action')}, confidence={llm_decision.get('confidence')}")
            self.logger.debug(f"[ROUTER] LLM decision details: {llm_decision}")
            # Record the full LLM decision payload for debugging.
            self.logger.debug("[ROUTER] Recorded LLM decision details")

            # 使用DecisionMaker进行增强分析（结合LLM决策）
            self.logger.debug("[ROUTER] 使用DecisionMaker进行增强分析")
            enhanced_decision = self.decision_maker.analyze_question(
                agent_input.content,
                conversation_history,
                llm_decision=llm_decision  # 传入LLM决策
            )
            self.logger.info(f"[ROUTER] 增强决策: action={enhanced_decision.get('action')}, confidence={enhanced_decision.get('confidence'):.2f}")
            self.logger.debug(f"[ROUTER] 增强决策详情: {enhanced_decision}")

            # 使用增强决策作为最终决策
            decision = enhanced_decision

            knowledge_enabled = agent_input.is_knowledge_enabled(default=False)
            self.logger.info(f"[ROUTER] 知识库增强开关: {knowledge_enabled}")
            # 验证决策
            if not self.decision_maker.validate_decision(decision):
                self.logger.warning("[ROUTER] 决策验证失败，使用默认决策")
                decision = {
                    "action": "direct_answer",
                    "confidence": 0.5,
                    "reason": "决策验证失败，使用默认直接回答",
                    "suggested_tools": []
                }

            execution_time_ms = int((time.time() - start_time) * 1000)

            # 更新执行记录为成功状态
            self.logger.debug("[ROUTER] 更新执行记录为成功状态")
            execution_update = AgentExecutionUpdate(
                output_data=decision,
                status="success",
                execution_time_ms=execution_time_ms
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)
            self.logger.debug(f"[ROUTER] 执行记录更新成功，耗时: {execution_time_ms}ms")

            # 创建输出
            self.logger.debug("[ROUTER] 创建输出对象")
            output = self._create_output(
                content=json.dumps(decision, ensure_ascii=False),
                status="success",
                execution_time_ms=execution_time_ms,
                execution_id=execution.execution_id,
                route_decision=decision,
                confidence=decision.get("confidence"),
                reasoning=decision.get("reason"),
                suggested_tools=decision.get("suggested_tools"),
            )

            self.logger.info("[ROUTER] ========== 路由分析完成 ==========")
            return output

        except Exception as e:
            self.logger.error(f"[ROUTER] 路由分析失败: {str(e)}", exc_info=True)

            execution_time_ms = int((time.time() - start_time) * 1000)

            # 保存失败记录
            self.logger.debug("[ROUTER] 创建失败执行记录")
            execution_create = AgentExecutionCreate(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content}
            )
            execution = self.execution_repo.create_execution(execution_create)
            self.logger.debug(f"[ROUTER] 失败执行记录创建成功: execution_id={execution.execution_id}")

            # 更新执行记录为失败状态
            self.logger.debug("[ROUTER] 更新执行记录为失败状态")
            execution_update = AgentExecutionUpdate(
                output_data={},
                status="failed",
                error_message=str(e),
                execution_time_ms=execution_time_ms
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)
            self.logger.debug("[ROUTER] 失败执行记录更新成功")

            self.logger.info("[ROUTER] ========== 路由分析失败 ==========")
            return self._create_output(
                content="",
                status="failed",
                error_message=str(e),
                execution_time_ms=execution_time_ms,
                execution_id=execution.execution_id
            )

    async def execute_stream(self, agent_input: AgentInput) -> AsyncGenerator[StreamChunk, None]:
        """执行流式路由流程并逐步输出路由分析结果。"""
        try:
            # 发送思考状态
            yield StreamChunk.create_thinking("正在分析问题类型...")

            # 执行非流式分析（路由决策不需要流式）
            output = await self.execute(agent_input)

            # 发送结果
            if output.is_success():
                yield StreamChunk.create_result(output.to_payload())
            else:
                yield StreamChunk.create_error(output.error_message or "路由分析失败")

        except Exception as e:
            self.logger.error(f"Router agent stream execution failed: {str(e)}")
            yield StreamChunk.create_error(str(e))

    def _parse_decision(self, response: str) -> dict:
        """解析模型返回内容并提取结构化路由决策。"""
        try:
            # 尝试解析JSON
            # 查找JSON代码块
            if "```json" in response:
                start = response.find("```json") + 7
                end = response.find("```", start)
                json_str = response[start:end].strip()
            elif "```" in response:
                start = response.find("```") + 3
                end = response.find("```", start)
                json_str = response[start:end].strip()
            else:
                json_str = response.strip()

            decision = json.loads(json_str)

            # 处理字段名不一致问题：prompt使用decision_type，代码使用action
            if "decision_type" in decision and "action" not in decision:
                decision["action"] = decision["decision_type"]
            elif "action" not in decision:
                self.logger.warning("Decision missing 'action' field, defaulting to direct_answer")
                decision["action"] = "direct_answer"

            # 处理reasoning字段（prompt使用reasoning，代码使用reason）
            if "reasoning" in decision and "reason" not in decision:
                decision["reason"] = decision["reasoning"]
            elif "reason" not in decision:
                decision["reason"] = "未提供决策理由"

            # 确保confidence字段存在
            if "confidence" not in decision:
                decision["confidence"] = 0.5

            # 第三阶段：支持direct_answer、retrieval、tool_call和multi_agent
            supported_actions = ["direct_answer", "retrieval", "tool_call", "multi_agent"]
            if decision["action"] not in supported_actions:
                self.logger.info(f"Action '{decision['action']}' not supported yet, using direct_answer")
                decision["action"] = "direct_answer"
                decision["reason"] = "该功能正在开发中，暂时使用直接回答"

            return decision

        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse decision JSON: {str(e)}")
            # 返回默认决策
            return {
                "action": "direct_answer",
                "confidence": 0.5,
                "reason": "无法解析路由决策，使用默认直接回答"
            }

    def _build_messages(self, user_content: str, conversation_history: list) -> list:
        """构造发送给路由模型的消息列表。"""
        messages = []

        # 添加系统提示词
        system_prompt = self._get_prompt("router_system_prompt")
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })
        else:
            self.logger.warning("router_system_prompt not found, using default")
            messages.append({
                "role": "system",
                "content": """你是一个智能路由助手，负责分析用户的问题并决定如何处理。

  你的任务是：
  1. 理解用户问题的意图和类型
  2. 判断问题是否需要检索知识库、调用工具或直接回答
  3. 返回一个JSON格式的决策结果

  决策类型说明：
  - direct_answer: 简单问候、常识问题、不需要额外信息的问题
  - retrieval: 需要查询知识库或文档的问题（企业内部信息、历史记录等）
  - tool_call: 需要调用外部工具的问题（计算、查询天气、搜索网络、翻译等）
  - multi_agent: 复杂任务，需要多个智能体协作

  系统可用工具列表：
  【本地工具】
  - calculator: 数学计算（加减乘除、数学函数）
  - web_search: 网络搜索（获取实时信息）
  - database_query: 数据库查询（企业内部数据）
  - translation: 多语言翻译
  - datetime: 时间日期查询和计算
  - novel_generator: AI小说生成
  - script_generator: AI脚本生成
  - content_optimizer: 内容优化（润色、改写等）

  【MCP工具（外部API）】
  - weather_mcp: 天气查询（当前天气和未来7天预报）
  - news_mcp: 新闻查询（最新新闻、关键词搜索）
  - wikipedia_mcp: 维基百科搜索
  - exchange_rate_mcp: 汇率查询和货币转换
  - ip_lookup_mcp: IP地址查询

  返回格式（必须是有效的JSON）：
  {{
    "decision_type": "决策类型（direct_answer/retrieval/tool_call/multi_agent）",
    "confidence": 0.95,
    "reasoning": "决策理由",
    "suggested_tools": ["工具名称"],
    "metadata": {{}}
  }}

  注意：decision_type为tool_call时需要填写suggested_tools，推荐1-3个工具

  决策指南：
  1. 如果问题明确需要某个工具（如"计算"、"天气"、"翻译"），选择tool_call并推荐对应工具
  2. 如果问题涉及企业内部信息、历史记录、文档查询，选择retrieval
  2.1 如果用户明确提到“知识库”“文档”“资料”“上传的文件”等范围，必须优先选择retrieval，不要选择web_search
  3. 如果是简单问候、常识问题、不需要额外信息，选择direct_answer
  4. 如果任务复杂需要多步骤处理，选择multi_agent

  注意事项：
  - 必须返回有效的JSON格式
  - confidence值在0-1之间，表示决策的置信度
  - reasoning要简洁明了，说明为什么选择这个决策
  - suggested_tools只在tool_call时需要，列出最相关的1-3个工具
  - 如果不确定，选择confidence较低的决策"""
            })

        # 格式化对话历史
        history_text = self._format_conversation_history(conversation_history)

        # 构建用户提示词
        user_prompt_template = self._get_prompt("router_user_prompt")
        if user_prompt_template:
            try:
                user_prompt = user_prompt_template.format(
                    question=user_content,
                    conversation_history=history_text
                )
            except KeyError as e:
                self.logger.warning(f"格式化用户提示词失败: {e}, 使用默认格式")
                user_prompt = f"用户问题：{user_content}\n\n对话历史：\n{history_text}\n\n请分析这个问题并返回路由决策。"
        else:
            user_prompt = f"用户问题：{user_content}\n\n对话历史：\n{history_text}\n\n请分析这个问题并返回路由决策。"

        messages.append({
            "role": "user",
            "content": user_prompt
        })

        return messages

    def _format_conversation_history(self, conversation_history: list) -> str:
        """把历史会话格式化为适合拼入 Prompt 的文本。"""
        if not conversation_history:
            no_history = self._get_prompt("no_history_placeholder")
            return no_history if no_history else "（这是新对话的第一条消息）"

        history_format = self._get_prompt("conversation_history_format")
        if not history_format:
            history_format = "{role}: {content}"

        # 移除YAML中的双花括号转义
        history_format = history_format.replace("{{", "{").replace("}}", "}")

        formatted_lines = []
        for msg in conversation_history[-5:]:  # 只保留最近5条
            if isinstance(msg, dict):
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                try:
                    formatted_lines.append(history_format.format(role=role, content=content))
                except KeyError as e:
                    self.logger.warning(f"格式化历史消息失败: {e}, 使用默认格式")
                    formatted_lines.append(f"{role}: {content}")

        return "\n".join(formatted_lines)

    def get_decision_type(self, agent_output: AgentOutput) -> str:
        """从 Agent 输出中提取决策动作类型。"""
        route_decision = agent_output.get_route_decision()
        if route_decision:
            return route_decision.get("action", "direct_answer")
        return "direct_answer"
