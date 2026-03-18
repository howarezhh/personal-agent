"""工作流执行器。

本模块负责整个问答链路中的工作流编排，统一使用 LangGraph 完成：
1. 规划：根据输入、路由结果和业务开关决定主分支；
2. 执行：根据规划结果进入对应执行节点；
3. 流式：通过 LangGraph 自定义流式写入器输出项目内部 `StreamChunk`。
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any, AsyncGenerator, Dict, TypedDict

from backend.agents.base.agent_input import AgentInput, GenerationAgentInput, ToolAgentInput
from backend.agents.base.stream_chunk import StreamChunk
from backend.contracts.errors import ErrorCode
from backend.utils.logger import get_logger
from backend.workflows.multi_agent_workflow import MultiAgentWorkflow, get_workflow_template
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph


def _get_agent_registry():
    """延迟加载 Agent 注册表，避免模块导入阶段耦合到具体 Agent 实现。"""
    from backend.agents.registry.agent_registry import get_agent_registry as _registry_factory

    return _registry_factory()

# =========================
# 路由动作常量
# =========================
# 这些值代表 Router 最终可能返回给执行器的主分支动作。
ACTION_DIRECT_ANSWER = "direct_answer"
ACTION_RETRIEVAL = "retrieval"
ACTION_TOOL_CALL = "tool_call"
ACTION_MULTI_AGENT = "multi_agent"

# =========================
# 工作流阶段常量
# =========================
# 这些值用于记录“本次请求经历了哪些阶段”，主要用于日志、SSE 元数据与排障。
WORKFLOW_STAGE_INTENT = "intent_recognition"
WORKFLOW_STAGE_RETRIEVAL = "retrieval"
WORKFLOW_STAGE_TOOL = "tool_call"
WORKFLOW_STAGE_GENERATION = "generation"
WORKFLOW_STAGE_MULTI_AGENT = "multi_agent"

# Router 允许返回的所有合法动作白名单。
# 一旦返回未知动作，执行器会自动回退到 direct_answer，避免整条链路不可用。
KNOWN_ACTIONS = {
    ACTION_DIRECT_ANSWER,
    ACTION_RETRIEVAL,
    ACTION_TOOL_CALL,
    ACTION_MULTI_AGENT,
}

# 错误消息脱敏规则：
# 用于屏蔽 token、password、api_key、Bearer Token 等敏感片段，
# 避免内部错误信息被原样透出到日志或返回给前端。
_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\b\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._\-]+"),
)


class _WorkflowPlanState(TypedDict, total=False):
    """工作流“规划阶段”共享状态。

    它不是最终回答，也不是某个 Agent 的输出对象，而是规划器内部在各个节点之间传递的状态容器。

    这里记录的信息主要包括：
    - 原始请求与工作副本；
    - 多轮对话历史；
    - 路由决策；
    - 最终要执行的 action；
    - 已经规划出的路径；
    - 规划阶段的错误与降级原因。
    """

    # 原始输入对象，保留最初请求语义，原则上不在规划过程中修改。
    agent_input: AgentInput
    # 工作流内部实际使用的输入副本，可安全附加 metadata 而不污染原始输入。
    working_input: AgentInput
    # 统一整理后的历史消息列表。
    history_messages: list
    # 知识库总开关是否开启。
    knowledge_enabled: bool
    # Router 返回的原始决策对象。
    decision: Dict[str, Any]
    # Router 原始 action。
    router_action: str
    # 实际最终要执行的 action，可能因为业务开关而与 router_action 不同。
    execution_action: str
    # 当前已规划出的阶段路径。
    execution_path: list[str]
    # 当前使用的规划引擎：langgraph。
    workflow_engine: str
    # 如果发生了回退或降级，这里记录原因。
    fallback_reason: str | None
    # 规划阶段结构化错误码。
    error_code: str | None
    # 规划阶段错误类型。
    error_type: str | None
    # 规划阶段错误消息。
    error_message: str | None


class _WorkflowExecutionState(TypedDict, total=False):
    """工作流“执行阶段”共享状态。"""

    agent_input: AgentInput
    working_input: AgentInput
    history_messages: list
    knowledge_enabled: bool
    plan_state: _WorkflowPlanState


class _WorkflowPlanner:
    """工作流规划器。

    它的职责非常单一：在真正执行 Retrieval / Tool / Generation 之前，
    先决定“本次请求应该走哪条路”。

    这样拆出来有两个好处：
    1. `WorkflowExecutor` 的执行逻辑更干净，不用把路径规划和实际执行揉在一起；
    2. 可以把 LangGraph 接入限制在规划层，避免大范围侵入现有执行实现。
    """

    def __init__(self, executor: "WorkflowExecutor"):
        """初始化规划器。

        参数：
        - executor：执行器本体。规划器复用它的 logger、router_agent 与输入克隆逻辑。
        """
        self.executor = executor
        self.logger = executor.logger
        self.router_agent = executor.router_agent
        # 规划阶段统一强制使用 LangGraph，不再保留手写规划兜底逻辑。
        self._compiled_graph = self._build_graph()

    async def plan(self, agent_input: AgentInput) -> _WorkflowPlanState:
        """对本次请求进行工作流路径规划。

        返回的是“规划结果状态”，而不是最终回答。
        执行器会根据这里得到的 execution_action 再进入对应执行分支。
        """
        # 先构造规划阶段的初始状态，确保后续所有节点消费的是统一状态对象。
        state = self._build_initial_state(agent_input)

        planned_state = await self._compiled_graph.ainvoke(state)
        planned_state["workflow_engine"] = planned_state.get("workflow_engine") or "langgraph"
        return planned_state

    def _build_graph(self):
        """构建 LangGraph 状态图。

        这里的节点只做“规划”动作，不做真正的流式执行：
        - validate_input：校验输入是否合法；
        - intent_recognition：调用 Router 识别主分支；
        - retrieval/tool/generation/multi_agent：追加阶段路径、必要时微调工作输入。
        """
        graph = StateGraph(_WorkflowPlanState)

        # 定义各个规划节点。
        graph.add_node("validate_input", self._validate_input_node)
        graph.add_node("intent_recognition", self._intent_recognition_node)
        graph.add_node("retrieval_stage", self._retrieval_stage_node)
        graph.add_node("tool_stage", self._tool_stage_node)
        graph.add_node("answer_generation_stage", self._generation_stage_node)
        graph.add_node("multi_agent_stage", self._multi_agent_stage_node)

        # 指定图的起点：任何请求都必须先做输入校验。
        graph.set_entry_point("validate_input")

        # 校验后只会分成两种情况：
        # - error：校验失败，直接结束；
        # - intent：校验成功，进入意图识别阶段。
        graph.add_conditional_edges(
            "validate_input",
            self._route_after_validation,
            {"error": END, "intent": "intent_recognition"},
        )

        # 路由识别后，根据 execution_action 决定进入哪条主分支。
        graph.add_conditional_edges(
            "intent_recognition",
            self._route_after_intent,
            {
                "error": END,
                ACTION_DIRECT_ANSWER: "answer_generation_stage",
                ACTION_RETRIEVAL: "retrieval_stage",
                ACTION_TOOL_CALL: "tool_stage",
                ACTION_MULTI_AGENT: "multi_agent_stage",
            },
        )

        # 检索与工具分支最终都要进入生成阶段，形成“先取上下文，再生成答案”的链路。
        graph.add_edge("retrieval_stage", "answer_generation_stage")
        graph.add_edge("tool_stage", "answer_generation_stage")

        # 生成分支与多 Agent 分支到此结束规划。
        graph.add_edge("answer_generation_stage", END)
        graph.add_edge("multi_agent_stage", END)
        return graph.compile()

    def _build_initial_state(self, agent_input: AgentInput) -> _WorkflowPlanState:
        """构建规划阶段的初始状态。

        关键点：
        - 先克隆一份 `working_input`，避免后续对 metadata 的追加污染原始输入；
        - 统一提前提取历史消息和知识库开关，减少后续节点重复判断。
        """
        working_input = self.executor._clone_agent_input(agent_input)
        return {
            "agent_input": agent_input,
            "working_input": working_input,
            "history_messages": self.executor._get_conversation_history(working_input),
            "knowledge_enabled": self.executor._is_knowledge_enabled(working_input),
            "execution_path": [],
            "fallback_reason": None,
            "error_code": None,
            "error_type": None,
            "error_message": None,
        }

    async def _validate_input_node(self, state: _WorkflowPlanState) -> _WorkflowPlanState:
        """输入校验节点。"""
        agent_input = state["agent_input"]
        is_valid, error_message = agent_input.validate()
        if is_valid:
            return state

        # 这里不抛异常，而是把结构化错误写进状态对象，
        # 让上层统一决定如何返回 error chunk。
        state["error_code"] = ErrorCode.WORKFLOW_INVALID_INPUT.value
        state["error_type"] = "validation_error"
        state["error_message"] = error_message or "工作流输入无效"
        return state

    async def _intent_recognition_node(self, state: _WorkflowPlanState) -> _WorkflowPlanState:
        """意图识别节点。

        这里会调用 Router，并做两层判断：
        1. Router 原始 decision 是什么；
        2. 当前业务开关是否允许执行该 decision。

        因此：
        - `router_action` 记录 Router 原始意图；
        - `execution_action` 记录最终真正执行的分支。
        """
        working_input = state["working_input"]
        router_output = await self.router_agent.execute(working_input)
        if not router_output.is_success():
            state["error_code"] = ErrorCode.WORKFLOW_ROUTER_FAILED.value
            state["error_type"] = "router_error"
            state["error_message"] = self.executor._safe_error_message(
                router_output.error_message,
                fallback="路由分析失败",
            )
            return state

        decision = router_output.get_route_decision() or {}
        router_action = decision.get("action", ACTION_DIRECT_ANSWER)
        if router_action not in KNOWN_ACTIONS:
            # 未知动作一律降级为直接回答，保证主链路稳定可用。
            router_action = ACTION_DIRECT_ANSWER
            state["fallback_reason"] = "unknown_router_action"

        execution_action = router_action
        if execution_action == ACTION_RETRIEVAL and not state.get("knowledge_enabled", True):
            # 即使 Router 判断应走检索，也必须遵守知识库总开关。
            execution_action = ACTION_DIRECT_ANSWER
            state["fallback_reason"] = "knowledge_base_disabled"

        # 保存规划结果，供执行器入口统一消费。
        state["decision"] = decision
        state["working_input"] = working_input.clone_with(route_decision=decision)
        state["router_action"] = decision.get("action", ACTION_DIRECT_ANSWER)
        state["execution_action"] = execution_action
        state["execution_path"] = [WORKFLOW_STAGE_INTENT]
        return state

    async def _retrieval_stage_node(self, state: _WorkflowPlanState) -> _WorkflowPlanState:
        """在规划路径中追加 retrieval 阶段。"""
        state["execution_path"] = [*state.get("execution_path", []), WORKFLOW_STAGE_RETRIEVAL]
        return state

    async def _tool_stage_node(self, state: _WorkflowPlanState) -> _WorkflowPlanState:
        """在规划路径中追加 tool 阶段，并注入 Router 推荐工具。"""
        state["execution_path"] = [*state.get("execution_path", []), WORKFLOW_STAGE_TOOL]
        decision = state.get("decision", {})
        suggested_tools = decision.get("suggested_tools", []) if isinstance(decision, dict) else []
        if suggested_tools:
            # 这里只修改 working_input 副本，不修改原始输入对象。
            # 这样 ToolAgent 可以感知候选工具缩小范围，但不会污染外部调用上下文。
            state["working_input"] = self.executor._create_tool_agent_input(
                state["working_input"],
                available_tools=suggested_tools,
            )
        return state

    async def _generation_stage_node(self, state: _WorkflowPlanState) -> _WorkflowPlanState:
        """在规划路径中追加 generation 阶段。"""
        state["execution_path"] = [*state.get("execution_path", []), WORKFLOW_STAGE_GENERATION]
        return state

    async def _multi_agent_stage_node(self, state: _WorkflowPlanState) -> _WorkflowPlanState:
        """在规划路径中追加 multi_agent 阶段。"""
        state["execution_path"] = [*state.get("execution_path", []), WORKFLOW_STAGE_MULTI_AGENT]
        decision = state.get("decision", {})
        suggested_tools = decision.get("suggested_tools", []) if isinstance(decision, dict) else []
        if suggested_tools:
            state["working_input"] = self.executor._create_tool_agent_input(
                state["working_input"],
                available_tools=suggested_tools,
            )
        return state

    @staticmethod
    def _route_after_validation(state: _WorkflowPlanState) -> str:
        """根据校验阶段结果，决定下一跳。"""
        return "error" if state.get("error_code") else "intent"

    @staticmethod
    def _route_after_intent(state: _WorkflowPlanState) -> str:
        """根据意图识别结果，决定主分支。"""
        if state.get("error_code"):
            return "error"
        return state.get("execution_action", ACTION_DIRECT_ANSWER)


class WorkflowExecutor:
    """工作流执行器。

    与 `_WorkflowPlanner` 的职责分工如下：
    - Planner：决定“走哪条路”；
    - Executor：负责“真的去执行”。

    因此本类的核心入口 `execute_workflow()` 分成两步：
    1. 先调用规划器拿到 plan_state；
    2. 再根据 execution_action 进入对应的执行分支。
    """

    def __init__(self):
        """初始化执行器和各类 Agent 依赖。"""
        self.logger = get_logger(self.__class__.__name__)

        registry = _get_agent_registry()
        # 执行器只依赖注册表中的标准 Agent，不再回退到散落的默认实例化逻辑。
        self.router_agent = self._require_agent(registry, "router")
        self.generation_agent = self._require_agent(registry, "generation")
        self.retrieval_agent = self._require_agent(registry, "retrieval")
        self.tool_agent = self._require_agent(registry, "tool")
        self.multi_agent_workflow = MultiAgentWorkflow()
        self.workflow_planner: _WorkflowPlanner | None = None
        self._compiled_execution_graph = self._build_execution_graph()

    @staticmethod
    def _require_agent(registry: Any, agent_type: str) -> Any:
        """从注册表获取必需 Agent，缺失时直接失败。"""
        agent = registry.create(agent_type)
        if agent is None:
            raise RuntimeError(f"Agent 未注册: {agent_type}")
        return agent

    @staticmethod
    def _truncate_text(value: Any, max_length: int = 120) -> str:
        """截断长文本，避免日志刷屏。"""
        text = str(value).replace("\n", "\\n")
        if len(text) <= max_length:
            return text
        return f"{text[:max_length]}..."

    def _summarize_payload(self, payload: Any) -> str:
        """生成日志摘要。

        目的不是完整打印 payload，而是输出一个足够排障但不过度冗长的摘要信息。
        """
        if payload is None:
            return "None"

        if isinstance(payload, dict):
            keys = list(payload.keys())
            key_preview = keys[:8]
            summary_parts = [f"dict(keys={key_preview}{'...' if len(keys) > 8 else ''})"]

            retrieval_results = payload.get("retrieval_results")
            if isinstance(retrieval_results, list):
                summary_parts.append(f"retrieval_results={len(retrieval_results)}")

            citations = payload.get("citations")
            if isinstance(citations, list):
                summary_parts.append(f"citations={len(citations)}")

            tool_result = payload.get("tool_result")
            if isinstance(tool_result, dict):
                summary_parts.append(f"tool_result_keys={list(tool_result.keys())[:6]}")

            return ", ".join(summary_parts)

        if isinstance(payload, list):
            item_type = type(payload[0]).__name__ if payload else "empty"
            return f"list(len={len(payload)}, item_type={item_type})"

        if isinstance(payload, str):
            return f"str(len={len(payload)}, preview='{self._truncate_text(payload)}')"

        try:
            json.dumps(payload)
            return f"{type(payload).__name__}({self._truncate_text(payload)})"
        except TypeError:
            return f"{type(payload).__name__}({self._truncate_text(repr(payload))})"

    def _safe_error_message(self, error: Any, fallback: str = "工作流执行失败") -> str:
        """生成安全的错误消息。

        核心策略：
        - 先把异常转成字符串；
        - 再做敏感信息脱敏；
        - 再做长度截断；
        - 最后根据异常类型决定是否保留异常类名。
        """
        if error is None:
            return fallback

        raw_message = str(error)
        for pattern in _SENSITIVE_PATTERNS:
            raw_message = pattern.sub("[REDACTED]", raw_message)

        message = self._truncate_text(raw_message, max_length=160).strip()
        if not message:
            return fallback

        # 如果本身就是字符串，直接返回脱敏后的文本即可。
        if isinstance(error, str):
            return message

        error_type = type(error).__name__
        # 对于过于泛化的异常类型，不额外附带类型名，避免返回文案显得冗余。
        if error_type in {"Exception", "RuntimeError"}:
            return message

        return f"{error_type}: {message}"

    @staticmethod
    def _extract_tool_failure(tool_result: Dict[str, Any] | None) -> Dict[str, Any]:
        """从工具失败结果中提取标准错误上下文。"""
        payload = tool_result or {}
        return {
            "error": payload.get("error") or "工具调用失败",
            "error_code": payload.get("error_code"),
            "error_type": payload.get("error_type"),
            "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        }

    @staticmethod
    def _get_conversation_history(agent_input: AgentInput) -> list:
        """获取对话历史的安全副本。"""
        return deepcopy(agent_input.get_conversation_history())

    def _ensure_metadata(self, agent_input: AgentInput) -> Dict[str, Any]:
        """复制 metadata，避免后续流程原地修改。"""
        return deepcopy(agent_input.metadata) if agent_input.metadata else {}


    def _clone_agent_input(
        self,
        agent_input: AgentInput,
        metadata_updates: Dict[str, Any] | None = None,
    ) -> AgentInput:
        """克隆 AgentInput。

        这是本文件非常关键的一个保护动作：
        - 工作流内部经常需要给 metadata 临时附加信息；
        - 如果直接改原始输入，容易造成分支之间互相污染；
        - 因此所有分支内修改上下文时，都尽量基于克隆对象操作。
        """
        metadata = self._ensure_metadata(agent_input)
        conversation_history = deepcopy(self._get_conversation_history(agent_input))
        workflow_context = agent_input.get_workflow_context()

        if metadata_updates:
            for key, value in metadata_updates.items():
                metadata[key] = deepcopy(value)

        return AgentInput.from_agent_input(
            agent_input,
            conversation_history=conversation_history,
            metadata=metadata,
            workflow_context=workflow_context.to_dict() if workflow_context else None,
        )

    def _create_tool_agent_input(
        self,
        agent_input: AgentInput,
        available_tools: list[str] | None = None,
    ) -> ToolAgentInput:
        metadata = self._ensure_metadata(agent_input)
        workflow_context = deepcopy(agent_input.get_workflow_context())
        return ToolAgentInput.from_agent_input(
            agent_input,
            conversation_history=self._get_conversation_history(agent_input),
            metadata=metadata,
            workflow_context=workflow_context,
            available_tools=deepcopy(available_tools),
            tool_timeout=getattr(agent_input, "tool_timeout", self.tool_agent.tool_timeout),
        )

    def _create_generation_agent_input(
        self,
        agent_input: AgentInput,
        *,
        retrieval_results: list[dict[str, Any]] | None = None,
        tool_result: dict[str, Any] | None = None,
    ) -> GenerationAgentInput:
        metadata = self._ensure_metadata(agent_input)
        workflow_context = deepcopy(agent_input.get_workflow_context())
        tool_results = [deepcopy(tool_result)] if tool_result is not None else None
        return GenerationAgentInput.from_agent_input(
            agent_input,
            conversation_history=self._get_conversation_history(agent_input),
            metadata=metadata,
            workflow_context=workflow_context,
            retrieval_results=deepcopy(retrieval_results),
            tool_results=tool_results,
        )

    @staticmethod
    def _extract_execution_id(payload: Any) -> str | None:
        if isinstance(payload, StreamChunk):
            if isinstance(payload.metadata, dict) and payload.metadata.get("execution_id"):
                return str(payload.metadata["execution_id"])
            return WorkflowExecutor._extract_execution_id(payload.content)

        if isinstance(payload, dict) and payload.get("execution_id"):
            return str(payload["execution_id"])

        return None

    def _is_knowledge_enabled(self, agent_input: AgentInput) -> bool:
        """判断知识库能力是否开启。

        设计为默认开启，只有显式传入 `False` 时才关闭。
        """
        return agent_input.is_knowledge_enabled(default=True)

    def _is_valid_workflow_config(self, workflow_config: Any) -> bool:
        """委托多 Agent 工作流对象校验配置是否合法。"""
        return self.multi_agent_workflow.is_valid_workflow_config(workflow_config)

    def _sanitize_multi_agent_workflow_config(
        self,
        workflow_config: Dict[str, Any],
        agent_input: AgentInput,
    ) -> tuple[Dict[str, Any] | None, bool]:
        """按运行期策略收敛工作流配置。

        当前主要约束：知识库关闭时，不允许在多 Agent 工作流中继续执行 retrieval 步骤。
        """

        knowledge_enabled = self._is_knowledge_enabled(agent_input)
        changed = False

        def _sanitize_steps(steps: Any) -> list[Dict[str, Any]] | None:
            nonlocal changed

            if not isinstance(steps, list):
                return None

            sanitized_steps: list[Dict[str, Any]] = []
            for step in steps:
                if not isinstance(step, dict):
                    return None

                step_type = step.get("type", "agent")
                if step_type == "condition":
                    sanitized_step = deepcopy(step)
                    true_branch = _sanitize_steps(step.get("true_branch", []))
                    false_branch = _sanitize_steps(step.get("false_branch", []))
                    if true_branch is None or false_branch is None:
                        return None
                    sanitized_step["true_branch"] = true_branch
                    sanitized_step["false_branch"] = false_branch
                    sanitized_steps.append(sanitized_step)
                    continue

                if step_type != "agent":
                    return None

                if step.get("agent_type") == ACTION_RETRIEVAL and not knowledge_enabled:
                    changed = True
                    continue

                sanitized_steps.append(deepcopy(step))

            return sanitized_steps

        sanitized_steps = _sanitize_steps(workflow_config.get("steps", []))
        if sanitized_steps is None:
            return None, changed

        if not sanitized_steps:
            return None, True

        sanitized_config = deepcopy(workflow_config)
        sanitized_config["steps"] = sanitized_steps
        return sanitized_config, changed

    def _resolve_multi_agent_workflow_config(
        self,
        agent_input: AgentInput,
        decision: Dict[str, Any],
    ) -> tuple[Dict[str, Any] | None, str | None]:
        """解析并收敛多 Agent 工作流配置。"""

        resolution_notes: list[str] = []
        workflow_config = decision.get("workflow_config")

        template_name = decision.get("workflow_template")
        if not self._is_valid_workflow_config(workflow_config) and template_name:
            template_config = get_workflow_template(template_name)
            if self._is_valid_workflow_config(template_config):
                self.logger.info(f"使用工作流模板: {template_name}")
                workflow_config = template_config
                resolution_notes.append(f"workflow_template:{template_name}")

        if not self._is_valid_workflow_config(workflow_config):
            self.logger.warning("[FLOW][MULTI_AGENT] invalid workflow_config")
            return None, "invalid_workflow_config"

        sanitized_config, sanitized = self._sanitize_multi_agent_workflow_config(workflow_config, agent_input)
        if sanitized_config is None or not self._is_valid_workflow_config(sanitized_config):
            self.logger.warning("[FLOW][MULTI_AGENT] workflow_config rejected by runtime policy")
            return None, "workflow_policy_invalid"

        if sanitized:
            resolution_notes.append("workflow_policy_sanitized")

        return sanitized_config, ",".join(resolution_notes) if resolution_notes else None

    def _get_workflow_planner(self) -> _WorkflowPlanner:
        """按需获取规划器实例。"""
        planner = getattr(self, "workflow_planner", None)
        if planner is None:
            planner = _WorkflowPlanner(self)
            self.workflow_planner = planner
        return planner

    def _build_trace_metadata(self, agent_input: AgentInput, **extra: Any) -> Dict[str, Any]:
        """构建统一链路元数据。

        这里会把 user_id / conversation_id / message_id / request_id 等追踪字段补齐，
        便于 SSE 层和日志层统一消费。
        """
        input_metadata = self._ensure_metadata(agent_input)
        metadata: Dict[str, Any] = {
            "user_id": agent_input.user_id or None,
            "conversation_id": agent_input.conversation_id or None,
            "message_id": agent_input.message_id or None,
            "request_id": agent_input.get_request_id() or input_metadata.get("request_id"),
            "execution_id": agent_input.get_execution_id() or input_metadata.get("execution_id"),
            "knowledge_base_id": agent_input.get_knowledge_base_id() or input_metadata.get("knowledge_base_id"),
            "document_id": agent_input.get_document_id() or input_metadata.get("document_id"),
        }

        # extra 中的值优先级更高，用于补充 error_code、workflow_path 等执行期信息。
        for key, value in extra.items():
            if value is not None:
                metadata[key] = value

        # 最后过滤掉值为 None 的字段，减少冗余元数据。
        return {key: value for key, value in metadata.items() if value is not None}

    def _augment_chunk(self, chunk: StreamChunk, agent_input: AgentInput, **extra: Any) -> StreamChunk:
        """为下游 Agent 返回的 chunk 补充统一链路元数据。"""
        extra = dict(extra)
        if extra.get("execution_id") is None:
            extra["execution_id"] = self._extract_execution_id(chunk)

        trace_metadata = self._build_trace_metadata(agent_input, **extra)
        metadata = deepcopy(chunk.metadata) if chunk.metadata else {}
        for key, value in trace_metadata.items():
            metadata[key] = value

        content = chunk.content
        if chunk.chunk_type == "error":
            content = self._safe_error_message(chunk.content, fallback="工作流执行失败")

        # 如果没有新增任何元数据，也没有发生内容脱敏，则直接返回原 chunk。
        if metadata == (chunk.metadata or {}) and content == chunk.content:
            return chunk

        return StreamChunk(
            chunk_id=chunk.chunk_id,
            chunk_type=chunk.chunk_type,
            content=content,
            metadata=metadata or None,
            timestamp=chunk.timestamp,
        )

    def _create_error_chunk(
        self,
        agent_input: AgentInput,
        error_message: str,
        error_code: str,
        error_type: str,
        **extra: Any,
    ) -> StreamChunk:
        """创建统一结构的 error chunk。"""
        return StreamChunk.create_error(
            error_message,
            **self._build_trace_metadata(
                agent_input,
                error_code=error_code,
                error_type=error_type,
                **extra,
            ),
        )

    def _create_thinking_chunk(self, agent_input: AgentInput, content: str, **extra: Any) -> StreamChunk:
        """创建统一结构的 thinking chunk。"""
        return StreamChunk.create_thinking(content, **self._build_trace_metadata(agent_input, **extra))

    def _build_execution_graph(self):
        """构建工作流执行图。"""
        graph = StateGraph(_WorkflowExecutionState)
        graph.add_node("plan", self._execution_plan_node)
        graph.add_node("plan_error", self._execution_plan_error_node)
        graph.add_node(ACTION_DIRECT_ANSWER, self._execution_direct_answer_node)
        graph.add_node(ACTION_RETRIEVAL, self._execution_retrieval_node)
        graph.add_node(ACTION_TOOL_CALL, self._execution_tool_node)
        graph.add_node(ACTION_MULTI_AGENT, self._execution_multi_agent_node)

        graph.add_edge(START, "plan")
        graph.add_conditional_edges(
            "plan",
            self._route_after_execution_plan,
            {
                "plan_error": "plan_error",
                ACTION_DIRECT_ANSWER: ACTION_DIRECT_ANSWER,
                ACTION_RETRIEVAL: ACTION_RETRIEVAL,
                ACTION_TOOL_CALL: ACTION_TOOL_CALL,
                ACTION_MULTI_AGENT: ACTION_MULTI_AGENT,
            },
        )
        graph.add_edge("plan_error", END)
        graph.add_edge(ACTION_DIRECT_ANSWER, END)
        graph.add_edge(ACTION_RETRIEVAL, END)
        graph.add_edge(ACTION_TOOL_CALL, END)
        graph.add_edge(ACTION_MULTI_AGENT, END)
        return graph.compile()

    async def _execution_plan_node(self, state: _WorkflowExecutionState) -> _WorkflowExecutionState:
        """规划并把结果写入执行状态。"""
        writer = get_stream_writer()
        working_input = state["agent_input"]
        writer(self._create_thinking_chunk(working_input, "正在分析问题类型..."))

        plan_state = await self._get_workflow_planner().plan(working_input)
        if plan_state.get("error_code"):
            plan_state["error_message"] = self._safe_error_message(
                plan_state.get("error_message"),
                fallback="工作流执行失败",
            )
            self.logger.error(
                "[FLOW] workflow_plan_failed: "
                f"error_code={plan_state.get('error_code')}, error={plan_state.get('error_message')}"
            )
            return {**state, "plan_state": plan_state}

        action = plan_state.get("execution_action")
        if action not in KNOWN_ACTIONS:
            plan_state["error_code"] = ErrorCode.WORKFLOW_EXECUTION_ERROR.value
            plan_state["error_type"] = "workflow_error"
            plan_state["error_message"] = f"未知工作流动作: {action}"
            self.logger.error(f"[FLOW] workflow_plan_invalid_action: action={action}")
            return {**state, "plan_state": plan_state}

        self.logger.info(
            "[FLOW] workflow_plan_ready: "
            f"engine={plan_state.get('workflow_engine')}, "
            f"router_action={plan_state.get('router_action', action)}, execution_action={action}, "
            f"path={plan_state.get('execution_path', [])}, "
            f"decision={self._summarize_payload(plan_state.get('decision', {}))}"
        )
        if plan_state.get("fallback_reason"):
            self.logger.info(f"[FLOW] workflow_plan_fallback: reason={plan_state.get('fallback_reason')}")
        return {**state, "plan_state": plan_state}

    @staticmethod
    def _route_after_execution_plan(state: _WorkflowExecutionState) -> str:
        """根据规划结果决定进入哪个执行节点。"""
        plan_state = state.get("plan_state", {})
        if plan_state.get("error_code"):
            return "plan_error"
        return str(plan_state.get("execution_action", ACTION_DIRECT_ANSWER))

    async def _execution_plan_error_node(self, state: _WorkflowExecutionState) -> _WorkflowExecutionState:
        """输出规划阶段错误。"""
        writer = get_stream_writer()
        plan_state = state.get("plan_state", {})
        planned_input = plan_state.get("working_input") or state["agent_input"]
        writer(
            self._create_error_chunk(
                planned_input,
                plan_state.get("error_message") or "工作流执行失败",
                plan_state.get("error_code") or ErrorCode.WORKFLOW_EXECUTION_ERROR.value,
                plan_state.get("error_type") or "workflow_error",
                workflow_engine=plan_state.get("workflow_engine"),
                workflow_path=plan_state.get("execution_path"),
                fallback_reason=plan_state.get("fallback_reason"),
            )
        )
        return state

    async def _stream_planned_execution_chunks(
        self,
        state: _WorkflowExecutionState,
        chunk_stream: AsyncGenerator[StreamChunk, None],
    ) -> _WorkflowExecutionState:
        """把执行分支产出的 chunk 统一补齐链路元数据后写回流。"""
        writer = get_stream_writer()
        plan_state = state.get("plan_state", {})
        planned_input = plan_state.get("working_input") or state["agent_input"]
        extra = {
            "workflow_engine": plan_state.get("workflow_engine"),
            "workflow_path": plan_state.get("execution_path"),
            "fallback_reason": plan_state.get("fallback_reason"),
        }
        async for chunk in chunk_stream:
            writer(self._augment_chunk(chunk, planned_input, **extra))
        return state

    async def _execution_direct_answer_node(self, state: _WorkflowExecutionState) -> _WorkflowExecutionState:
        """执行直接回答分支。"""
        plan_state = state.get("plan_state", {})
        planned_input = plan_state.get("working_input") or state["agent_input"]
        return await self._stream_planned_execution_chunks(
            state,
            self._execute_direct_answer_workflow(planned_input),
        )

    async def _execution_retrieval_node(self, state: _WorkflowExecutionState) -> _WorkflowExecutionState:
        """执行检索增强分支。"""
        plan_state = state.get("plan_state", {})
        planned_input = plan_state.get("working_input") or state["agent_input"]
        return await self._stream_planned_execution_chunks(
            state,
            self._execute_retrieval_workflow(planned_input),
        )

    async def _execution_tool_node(self, state: _WorkflowExecutionState) -> _WorkflowExecutionState:
        """执行工具调用分支。"""
        plan_state = state.get("plan_state", {})
        planned_input = plan_state.get("working_input") or state["agent_input"]
        return await self._stream_planned_execution_chunks(
            state,
            self._execute_tool_call_workflow(planned_input),
        )

    async def _execution_multi_agent_node(self, state: _WorkflowExecutionState) -> _WorkflowExecutionState:
        """执行多 Agent 分支。"""
        plan_state = state.get("plan_state", {})
        planned_input = plan_state.get("working_input") or state["agent_input"]
        decision = plan_state.get("decision", {})
        return await self._stream_planned_execution_chunks(
            state,
            self._execute_multi_agent_workflow(planned_input, decision),
        )

    async def execute_workflow(self, agent_input: AgentInput) -> AsyncGenerator[StreamChunk, None]:
        """执行完整工作流。"""
        working_input = self._clone_agent_input(agent_input)
        history_messages = self._get_conversation_history(working_input)
        knowledge_enabled = self._is_knowledge_enabled(working_input)

        self.logger.info(
            "[FLOW] workflow_start: "
            f"user_id={working_input.user_id}, "
            f"conversation_id={working_input.conversation_id}, "
            f"message_id={working_input.message_id}, "
            f"question_len={len(working_input.content or '')}, "
            f"history_count={len(history_messages)}, "
            f"knowledge_enabled={knowledge_enabled}"
        )

        initial_state: _WorkflowExecutionState = {
            "agent_input": working_input,
            "working_input": working_input,
            "history_messages": history_messages,
            "knowledge_enabled": knowledge_enabled,
        }

        try:
            async for event in self._compiled_execution_graph.astream(initial_state, stream_mode="custom"):
                if isinstance(event, StreamChunk):
                    yield event
        except Exception as error:
            safe_error = self._safe_error_message(error)
            self.logger.error(f"工作流执行失败: {safe_error}")
            yield self._create_error_chunk(
                working_input,
                safe_error,
                ErrorCode.WORKFLOW_EXECUTION_ERROR.value,
                "execution_error",
            )

    async def _execute_direct_answer_workflow(
        self,
        agent_input: AgentInput,
    ) -> AsyncGenerator[StreamChunk, None]:
        """执行直接回答工作流。

        特点：
        - 不做检索；
        - 不做工具调用；
        - 直接把请求交给 GenerationAgent 流式输出。
        """
        self.logger.info(
            "[FLOW][DIRECT] start generation_agent.execute_stream: "
            f"conversation_id={agent_input.conversation_id}, message_id={agent_input.message_id}"
        )

        async for chunk in self.generation_agent.execute_stream(agent_input):
            yield chunk

    async def _execute_retrieval_workflow(
        self,
        agent_input: AgentInput,
    ) -> AsyncGenerator[StreamChunk, None]:
        """执行检索增强工作流。

        典型链路：
        1. 调 RetrievalAgent；
        2. 收集最终 retrieval_results；
        3. 若无结果，则回退到普通生成；
        4. 若有结果，则调用 GenerationAgent 的带上下文生成接口。
        """
        self.logger.info(
            "[FLOW][RETRIEVAL] start retrieval workflow: "
            f"conversation_id={agent_input.conversation_id}, message_id={agent_input.message_id}"
        )

        # 用于缓存检索阶段最终产出的检索结果列表。
        retrieval_results = []
        async for chunk in self.retrieval_agent.execute_stream(agent_input):
            if chunk.chunk_type == "thinking":
                # thinking 只透传，不做额外处理。
                self.logger.debug(
                    "[FLOW][RETRIEVAL] thinking_chunk="
                    f"{self._summarize_payload(chunk.content)}"
                )
                yield chunk
                continue

            if chunk.chunk_type == "error":
                # 检索阶段报错时，补充统一错误元数据后直接结束该分支。
                self.logger.error(
                    "[FLOW][RETRIEVAL] error_chunk="
                    f"{self._summarize_payload(chunk.content)}"
                )
                yield self._augment_chunk(
                    chunk,
                    agent_input,
                    error_code=(chunk.metadata or {}).get("error_code") or ErrorCode.WORKFLOW_EXECUTION_ERROR.value,
                    error_type=(chunk.metadata or {}).get("error_type") or "retrieval_error",
                )
                return

            if chunk.chunk_type == "result":
                # RetrievalAgent 的最终结果通常放在 result chunk 中。
                result_payload = chunk.content if isinstance(chunk.content, dict) else {}
                self.logger.info(
                    "[FLOW][RETRIEVAL] result_chunk="
                    f"{self._summarize_payload(result_payload)}"
                )
                retrieval_results = result_payload.get("retrieval_results", []) or []
                continue

            # 其他类型 chunk（如 content / metadata）原样透传，保证兼容性。
            yield chunk

        if not retrieval_results:
            # 没有检索结果不是硬错误，而是业务级降级：继续走普通生成。
            self.logger.info("[FLOW][RETRIEVAL] no retrieval results, fallback to generation")
            yield self._create_thinking_chunk(
                agent_input,
                "未找到相关信息，使用通用知识回答...",
                fallback_reason="retrieval_no_result",
                error_code=ErrorCode.RETRIEVAL_NO_RESULT.value,
            )
            async for chunk in self.generation_agent.execute_stream(agent_input):
                yield chunk
            return

        # 生成阶段只需要历史消息等通用上下文，不把 retrieval_results 塞进 metadata，
        # 而是作为显式参数传给 generate_with_context_stream，避免 metadata 承载主流程数据。
        generation_input = self._create_generation_agent_input(
            agent_input,
            retrieval_results=retrieval_results,
        )

        self.logger.info(
            "[FLOW][RETRIEVAL] handoff_to_generation_with_context: "
            f"retrieval_results={len(retrieval_results)}, "
            f"sample={self._summarize_payload(retrieval_results[0] if retrieval_results else {})}"
        )
        async for chunk in self.generation_agent.generate_with_context_stream(
            generation_input,
            retrieval_results,
        ):
            yield chunk

    async def _execute_tool_call_workflow(
        self,
        agent_input: AgentInput,
    ) -> AsyncGenerator[StreamChunk, None]:
        """执行工具调用工作流。

        典型链路：
        1. 调 ToolAgent 选择工具并执行；
        2. 收集 tool_call / result / error；
        3. 如果工具判断无需调用，则回退到检索或直接生成；
        4. 如果工具调用失败，则回退到直接生成；
        5. 如果工具调用成功，则把工具结果显式传给 GenerationAgent。
        """
        self.logger.info(
            "[FLOW][TOOL] start tool workflow: "
            f"conversation_id={agent_input.conversation_id}, message_id={agent_input.message_id}"
        )

        # tool_result 保存工具阶段最终结果，tool_name 用于日志和错误元数据。
        tool_result = None
        tool_name = None

        async for chunk in self.tool_agent.execute_stream(agent_input):
            if chunk.chunk_type == "thinking":
                self.logger.debug(
                    "[FLOW][TOOL] thinking_chunk="
                    f"{self._summarize_payload(chunk.content)}"
                )
                yield chunk
                continue

            if chunk.chunk_type == "tool_call":
                # tool_call chunk 往往会携带工具名、入参、执行状态等元数据。
                tool_call_data = chunk.content if isinstance(chunk.content, dict) else (chunk.metadata or {})
                self.logger.info(
                    "[FLOW][TOOL] tool_call_chunk="
                    f"{self._summarize_payload(tool_call_data)}"
                )
                tool_name = tool_call_data.get("tool_name", tool_name)
                yield chunk
                continue

            if chunk.chunk_type == "error":
                # 工具阶段出现硬错误时，优先降级到普通生成，避免整条回答链路直接失败。
                safe_error = self._safe_error_message(chunk.content, fallback="工具调用失败")
                error_code = (chunk.metadata or {}).get("error_code") or ErrorCode.WORKFLOW_EXECUTION_ERROR.value
                error_type = (chunk.metadata or {}).get("error_type") or "tool_error"
                self.logger.error(
                    "[FLOW][TOOL] error_chunk="
                    f"{self._summarize_payload(safe_error)}"
                )
                yield self._create_thinking_chunk(
                    agent_input,
                    f"工具调用失败: {safe_error}，使用通用知识回答...",
                    error_code=error_code,
                    error_type=error_type,
                    tool_name=tool_name,
                    fallback_reason="tool_error_fallback",
                )
                async for gen_chunk in self.generation_agent.execute_stream(agent_input):
                    yield gen_chunk
                return

            if chunk.chunk_type == "result":
                # ToolAgent 的最终执行结果通常通过 result chunk 返回。
                result_payload = chunk.content if isinstance(chunk.content, dict) else {}
                self.logger.info(
                    "[FLOW][TOOL] result_chunk="
                    f"{self._summarize_payload(result_payload)}"
                )
                tool_result = result_payload

                # 特殊情况：工具选择器判断其实不需要工具。
                if result_payload.get("no_tool_needed"):
                    route_action = result_payload.get("route_action")
                    if route_action == ACTION_RETRIEVAL and self._is_knowledge_enabled(agent_input):
                        # 工具阶段发现这是知识库问题，则切换到检索分支。
                        self.logger.info("[FLOW][TOOL] no_tool_needed=true, reroute_to=retrieval")
                        yield self._create_thinking_chunk(
                            agent_input,
                            "检测到这是知识库问题，切换到检索流程...",
                            fallback_reason="tool_route_to_retrieval",
                        )
                        async for retrieval_chunk in self._execute_retrieval_workflow(agent_input):
                            yield retrieval_chunk
                    else:
                        # 否则直接降级到普通生成。
                        self.logger.info("[FLOW][TOOL] no_tool_needed=true, fallback to generation")
                        yield self._create_thinking_chunk(
                            agent_input,
                            "无需使用工具，直接回答...",
                            fallback_reason="tool_not_needed",
                        )
                        async for gen_chunk in self.generation_agent.execute_stream(agent_input):
                            yield gen_chunk
                    return
                continue

            # 其他类型 chunk 原样透传。
            yield chunk

        if not tool_result:
            # 理论上工具阶段应返回 result；若没有，统一降级到普通生成。
            self.logger.warning("[FLOW][TOOL] tool_result_missing, fallback to generation")
            yield self._create_thinking_chunk(
                agent_input,
                "工具调用未返回结果，使用通用知识回答...",
                fallback_reason="tool_result_missing",
            )
            async for chunk in self.generation_agent.execute_stream(agent_input):
                yield chunk
            return

        # 提取工具执行结果中的真正 success / error 信息。
        tool_failure_payload = tool_result.get("tool_result")
        tool_failure = tool_failure_payload if isinstance(tool_failure_payload, dict) else {}
        if not tool_failure.get("success"):
            extracted_failure = self._extract_tool_failure(tool_failure)
            error_msg = self._safe_error_message(extracted_failure.get("error"), fallback="工具调用失败")
            self.logger.warning(
                "[FLOW][TOOL] tool_result_failed, fallback to generation: "
                f"error={error_msg}, error_code={extracted_failure.get('error_code')}, "
                f"payload={self._summarize_payload(tool_result)}"
            )
            yield self._create_thinking_chunk(
                agent_input,
                f"工具调用失败: {error_msg}，使用通用知识回答...",
                error_code=extracted_failure.get("error_code"),
                error_type=extracted_failure.get("error_type"),
                tool_name=tool_name,
                fallback_reason="tool_failure",
            )
            async for chunk in self.generation_agent.execute_stream(agent_input):
                yield chunk
            return

        # 工具成功时，只把通用上下文放进 metadata，真正的 tool_result 通过显式参数传递。
        generation_input = self._create_generation_agent_input(
            agent_input,
            tool_result=tool_result,
        )

        self.logger.info(
            "[FLOW][TOOL] tool_result_success, handoff_to_generation: "
            f"tool_name={tool_name}, payload={self._summarize_payload(tool_result)}"
        )
        async for chunk in self.generation_agent.generate_with_tool_result_stream(
            generation_input,
            tool_result,
        ):
            yield chunk

    async def _execute_multi_agent_workflow(
        self,
        agent_input: AgentInput,
        decision: Dict[str, Any],
    ) -> AsyncGenerator[StreamChunk, None]:
        """执行多 Agent 工作流。

        这里的重点不是自己编排每一步，而是：
        - 先解析 Router 提供的 workflow_config / workflow_template；
        - 再把最终确认过的配置交给 `MultiAgentWorkflow` 执行。
        """
        self.logger.info(
            "[FLOW][MULTI_AGENT] start: "
            f"decision={self._summarize_payload(decision)}"
        )

        workflow_config, config_resolution_note = self._resolve_multi_agent_workflow_config(agent_input, decision)

        if workflow_config is None:
            self.logger.error("[FLOW][MULTI_AGENT] workflow_config_resolution_failed")
            yield self._create_error_chunk(
                agent_input,
                "多 Agent 工作流配置无效",
                ErrorCode.WORKFLOW_INVALID_INPUT.value,
                "workflow_config_error",
                workflow_type=ACTION_MULTI_AGENT,
            )
            return

        self.logger.info(
            "[FLOW][MULTI_AGENT] workflow_config="
            f"{self._summarize_payload(workflow_config)}"
        )
        if config_resolution_note:
            self.logger.info(f"[FLOW][MULTI_AGENT] config_resolution={config_resolution_note}")

        async for chunk in self.multi_agent_workflow.execute(agent_input, workflow_config):
            # 多 Agent 流程通常更复杂，因此对 result / error / tool_call 等关键块额外记日志。
            if chunk.chunk_type in ("result", "error", "tool_call"):
                self.logger.info(
                    "[FLOW][MULTI_AGENT] chunk="
                    f"type={chunk.chunk_type}, payload={self._summarize_payload(chunk.content)}"
                )
            yield chunk

    def get_workflow_type(self, action: str) -> str:
        """把内部 action 转成人类可读的工作流名称。"""
        workflow_types = {
            ACTION_DIRECT_ANSWER: "直接回答工作流",
            ACTION_RETRIEVAL: "检索增强工作流",
            ACTION_TOOL_CALL: "工具调用工作流",
            ACTION_MULTI_AGENT: "多Agent协作工作流",
        }
        return workflow_types.get(action, "未知工作流")
