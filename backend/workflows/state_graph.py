"""工作流状态图模块。

该模块定义了工作流可经历的状态、动作以及状态转换规则，主要职责包括：
1. 维护工作流状态机的唯一规则来源；
2. 提供合法状态转换校验；
3. 为工作流执行器和多 Agent 工作流提供统一状态推进能力；
4. 提供状态路径查询与文本可视化能力，便于调试和排障。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from backend.utils.logger import get_logger


class WorkflowState(Enum):
    """工作流状态枚举。

    这些状态描述的是“当前工作流运行到了哪个阶段”，而不是单个 Agent 的内部状态。
    """

    INIT = "init"  # 初始状态，工作流刚创建但尚未开始执行。
    ROUTING = "routing"  # 路由分析阶段，判断后续该走哪条流程。
    RETRIEVING = "retrieving"  # 知识库检索阶段。
    TOOL_CALLING = "tool_calling"  # 外部工具调用阶段。
    GENERATING = "generating"  # 生成最终回答阶段。
    COMPLETED = "completed"  # 已完成。
    FAILED = "failed"  # 已失败。


class WorkflowAction(Enum):
    """工作流动作枚举。

    动作表示“导致状态变化的事件”，同一状态可以根据不同动作流向不同下一状态。
    """

    START = "start"  # 启动工作流。
    ROUTE = "route"  # 执行路由分析。
    RETRIEVE = "retrieve"  # 执行知识检索。
    CALL_TOOL = "call_tool"  # 执行工具调用。
    GENERATE = "generate"  # 执行答案生成。
    COMPLETE = "complete"  # 标记流程完成。
    FAIL = "fail"  # 标记流程失败。


@dataclass
class StateTransition:
    """单条状态转换规则。"""

    from_state: WorkflowState
    action: WorkflowAction
    to_state: WorkflowState
    # `condition` 当前主要用于记录说明性信息，便于文档化和调试；
    # 真正的业务判断通常发生在路由器或执行器中，而不是在状态图内部求值。
    condition: Optional[str] = None


class WorkflowStateGraph:
    """工作流状态图。

    功能：
    1. 定义工作流的全部合法状态；
    2. 定义状态之间的允许转换关系；
    3. 为执行阶段提供快速状态查询与校验；
    4. 通过单一状态机降低流程控制逻辑分散在各处的风险。
    """

    def __init__(self):
        """初始化状态图并构建转换索引。"""
        self.logger = get_logger(self.__class__.__name__)

        # 这里集中维护所有工作流状态转换规则，属于工作流状态机的唯一事实源。
        self.transitions: List[StateTransition] = [
            # 初始化 → 路由。
            StateTransition(
                WorkflowState.INIT,
                WorkflowAction.START,
                WorkflowState.ROUTING,
            ),
            # 路由 → 检索：问题被判定为知识检索型问题时进入该分支。
            StateTransition(
                WorkflowState.ROUTING,
                WorkflowAction.RETRIEVE,
                WorkflowState.RETRIEVING,
                "action == 'retrieval'",
            ),
            # 路由 → 工具调用：当路由器判断需要外部工具时进入该分支。
            StateTransition(
                WorkflowState.ROUTING,
                WorkflowAction.CALL_TOOL,
                WorkflowState.TOOL_CALLING,
                "action == 'tool_call'",
            ),
            # 路由 → 生成：当无需检索也无需工具时直接生成答案。
            StateTransition(
                WorkflowState.ROUTING,
                WorkflowAction.GENERATE,
                WorkflowState.GENERATING,
                "action == 'direct_answer'",
            ),
            # 检索 → 生成：检索结果会作为生成阶段的上下文输入。
            StateTransition(
                WorkflowState.RETRIEVING,
                WorkflowAction.GENERATE,
                WorkflowState.GENERATING,
            ),
            # 工具调用 → 生成：工具结果会作为生成阶段的上下文输入。
            StateTransition(
                WorkflowState.TOOL_CALLING,
                WorkflowAction.GENERATE,
                WorkflowState.GENERATING,
            ),
            # 生成 → 完成：标准主流程结束路径。
            StateTransition(
                WorkflowState.GENERATING,
                WorkflowAction.COMPLETE,
                WorkflowState.COMPLETED,
            ),
            # 任何运行中的主要状态都允许直接进入失败态，便于统一处理异常终止。
            StateTransition(
                WorkflowState.INIT,
                WorkflowAction.FAIL,
                WorkflowState.FAILED,
            ),
            StateTransition(
                WorkflowState.ROUTING,
                WorkflowAction.FAIL,
                WorkflowState.FAILED,
            ),
            StateTransition(
                WorkflowState.RETRIEVING,
                WorkflowAction.FAIL,
                WorkflowState.FAILED,
            ),
            StateTransition(
                WorkflowState.TOOL_CALLING,
                WorkflowAction.FAIL,
                WorkflowState.FAILED,
            ),
            StateTransition(
                WorkflowState.GENERATING,
                WorkflowAction.FAIL,
                WorkflowState.FAILED,
            ),
        ]

        # 将线性规则列表转换成嵌套字典，后续查询复杂度更低。
        self._build_transition_map()

    def _build_transition_map(self):
        """构建状态转换映射表。"""
        self.transition_map: Dict[WorkflowState, Dict[WorkflowAction, WorkflowState]] = {}

        for transition in self.transitions:
            if transition.from_state not in self.transition_map:
                self.transition_map[transition.from_state] = {}

            self.transition_map[transition.from_state][transition.action] = transition.to_state

    def can_transition(
        self,
        from_state: WorkflowState,
        action: WorkflowAction,
    ) -> bool:
        """检查是否允许进行状态转换。"""
        return (
            from_state in self.transition_map
            and action in self.transition_map[from_state]
        )

    def get_next_state(
        self,
        from_state: WorkflowState,
        action: WorkflowAction,
    ) -> Optional[WorkflowState]:
        """获取在给定动作下的下一状态。"""
        if not self.can_transition(from_state, action):
            self.logger.warning(
                f"无效的状态转换: {from_state.value} --{action.value}--> ?"
            )
            return None

        return self.transition_map[from_state][action]

    def get_available_actions(
        self,
        state: WorkflowState,
    ) -> List[WorkflowAction]:
        """获取当前状态下允许执行的动作列表。"""
        if state not in self.transition_map:
            return []

        return list(self.transition_map[state].keys())

    def is_terminal_state(self, state: WorkflowState) -> bool:
        """判断当前状态是否为终止状态。"""
        return state in [WorkflowState.COMPLETED, WorkflowState.FAILED]

    def get_workflow_path(
        self,
        action_type: str,
    ) -> List[WorkflowState]:
        """获取某类工作流对应的标准状态路径。"""
        paths = {
            "direct_answer": [
                WorkflowState.INIT,
                WorkflowState.ROUTING,
                WorkflowState.GENERATING,
                WorkflowState.COMPLETED,
            ],
            "retrieval": [
                WorkflowState.INIT,
                WorkflowState.ROUTING,
                WorkflowState.RETRIEVING,
                WorkflowState.GENERATING,
                WorkflowState.COMPLETED,
            ],
            "tool_call": [
                WorkflowState.INIT,
                WorkflowState.ROUTING,
                WorkflowState.TOOL_CALLING,
                WorkflowState.GENERATING,
                WorkflowState.COMPLETED,
            ],
        }

        return paths.get(action_type, [])

    def visualize(self) -> str:
        """以文本形式可视化状态图。"""
        lines = ["Workflow State Graph:", "=" * 50]

        for from_state in WorkflowState:
            if from_state in self.transition_map:
                lines.append(f"\n{from_state.value}:")
                for action, to_state in self.transition_map[from_state].items():
                    lines.append(f"  --{action.value}--> {to_state.value}")

        lines.append("=" * 50)
        return "\n".join(lines)


# 全局状态图单例。
_state_graph = None


def get_state_graph() -> WorkflowStateGraph:
    """获取全局状态图实例。"""
    global _state_graph
    if _state_graph is None:
        _state_graph = WorkflowStateGraph()
    return _state_graph