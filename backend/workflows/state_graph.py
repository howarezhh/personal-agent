"""
状态图
定义Agent工作流的状态转换图
"""

from enum import Enum
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
from backend.utils.logger import get_logger


class WorkflowState(Enum):
    """工作流状态枚举"""
    INIT = "init"  # 初始状态
    ROUTING = "routing"  # 路由分析中
    RETRIEVING = "retrieving"  # 检索中
    TOOL_CALLING = "tool_calling"  # 工具调用中
    GENERATING = "generating"  # 生成回答中
    COMPLETED = "completed"  # 完成
    FAILED = "failed"  # 失败


class WorkflowAction(Enum):
    """工作流动作枚举"""
    START = "start"  # 开始
    ROUTE = "route"  # 路由
    RETRIEVE = "retrieve"  # 检索
    CALL_TOOL = "call_tool"  # 调用工具
    GENERATE = "generate"  # 生成
    COMPLETE = "complete"  # 完成
    FAIL = "fail"  # 失败


@dataclass
class StateTransition:
    """状态转换"""
    from_state: WorkflowState
    action: WorkflowAction
    to_state: WorkflowState
    condition: Optional[str] = None  # 转换条件描述


class WorkflowStateGraph:
    """
    工作流状态图
    
    功能：
    1. 定义工作流的所有可能状态
    2. 定义状态之间的转换规则
    3. 验证状态转换的合法性
    4. 提供状态查询功能
    """
    
    def __init__(self):
        """初始化状态图"""
        self.logger = get_logger(self.__class__.__name__)
        
        # 定义所有状态转换
        self.transitions: List[StateTransition] = [
            # 初始化 → 路由
            StateTransition(
                WorkflowState.INIT,
                WorkflowAction.START,
                WorkflowState.ROUTING
            ),
            
            # 路由 → 检索（如果需要检索）
            StateTransition(
                WorkflowState.ROUTING,
                WorkflowAction.RETRIEVE,
                WorkflowState.RETRIEVING,
                "action == 'retrieval'"
            ),
            
            # 路由 → 工具调用（如果需要工具）
            StateTransition(
                WorkflowState.ROUTING,
                WorkflowAction.CALL_TOOL,
                WorkflowState.TOOL_CALLING,
                "action == 'tool_call'"
            ),
            
            # 路由 → 生成（如果直接回答）
            StateTransition(
                WorkflowState.ROUTING,
                WorkflowAction.GENERATE,
                WorkflowState.GENERATING,
                "action == 'direct_answer'"
            ),
            
            # 检索 → 生成
            StateTransition(
                WorkflowState.RETRIEVING,
                WorkflowAction.GENERATE,
                WorkflowState.GENERATING
            ),
            
            # 工具调用 → 生成
            StateTransition(
                WorkflowState.TOOL_CALLING,
                WorkflowAction.GENERATE,
                WorkflowState.GENERATING
            ),
            
            # 生成 → 完成
            StateTransition(
                WorkflowState.GENERATING,
                WorkflowAction.COMPLETE,
                WorkflowState.COMPLETED
            ),
            
            # 任何状态 → 失败
            StateTransition(
                WorkflowState.INIT,
                WorkflowAction.FAIL,
                WorkflowState.FAILED
            ),
            StateTransition(
                WorkflowState.ROUTING,
                WorkflowAction.FAIL,
                WorkflowState.FAILED
            ),
            StateTransition(
                WorkflowState.RETRIEVING,
                WorkflowAction.FAIL,
                WorkflowState.FAILED
            ),
            StateTransition(
                WorkflowState.TOOL_CALLING,
                WorkflowAction.FAIL,
                WorkflowState.FAILED
            ),
            StateTransition(
                WorkflowState.GENERATING,
                WorkflowAction.FAIL,
                WorkflowState.FAILED
            ),
        ]
        
        # 构建转换映射表（用于快速查询）
        self._build_transition_map()
    
    def _build_transition_map(self):
        """构建状态转换映射表"""
        self.transition_map: Dict[WorkflowState, Dict[WorkflowAction, WorkflowState]] = {}
        
        for transition in self.transitions:
            if transition.from_state not in self.transition_map:
                self.transition_map[transition.from_state] = {}
            
            self.transition_map[transition.from_state][transition.action] = transition.to_state
    
    def can_transition(
        self,
        from_state: WorkflowState,
        action: WorkflowAction
    ) -> bool:
        """
        检查是否可以进行状态转换
        
        Args:
            from_state: 当前状态
            action: 要执行的动作
        
        Returns:
            是否可以转换
        """
        return (
            from_state in self.transition_map and
            action in self.transition_map[from_state]
        )
    
    def get_next_state(
        self,
        from_state: WorkflowState,
        action: WorkflowAction
    ) -> Optional[WorkflowState]:
        """
        获取下一个状态
        
        Args:
            from_state: 当前状态
            action: 要执行的动作
        
        Returns:
            下一个状态，如果不能转换则返回None
        """
        if not self.can_transition(from_state, action):
            self.logger.warning(
                f"无效的状态转换: {from_state.value} --{action.value}--> ?"
            )
            return None
        
        return self.transition_map[from_state][action]
    
    def get_available_actions(
        self,
        state: WorkflowState
    ) -> List[WorkflowAction]:
        """
        获取当前状态下可用的动作
        
        Args:
            state: 当前状态
        
        Returns:
            可用动作列表
        """
        if state not in self.transition_map:
            return []
        
        return list(self.transition_map[state].keys())
    
    def is_terminal_state(self, state: WorkflowState) -> bool:
        """
        判断是否是终止状态
        
        Args:
            state: 状态
        
        Returns:
            是否是终止状态
        """
        return state in [WorkflowState.COMPLETED, WorkflowState.FAILED]
    
    def get_workflow_path(
        self,
        action_type: str
    ) -> List[WorkflowState]:
        """
        获取特定工作流类型的状态路径
        
        Args:
            action_type: 工作流类型（direct_answer/retrieval/tool_call）
        
        Returns:
            状态路径列表
        """
        paths = {
            "direct_answer": [
                WorkflowState.INIT,
                WorkflowState.ROUTING,
                WorkflowState.GENERATING,
                WorkflowState.COMPLETED
            ],
            "retrieval": [
                WorkflowState.INIT,
                WorkflowState.ROUTING,
                WorkflowState.RETRIEVING,
                WorkflowState.GENERATING,
                WorkflowState.COMPLETED
            ],
            "tool_call": [
                WorkflowState.INIT,
                WorkflowState.ROUTING,
                WorkflowState.TOOL_CALLING,
                WorkflowState.GENERATING,
                WorkflowState.COMPLETED
            ]
        }
        
        return paths.get(action_type, [])
    
    def visualize(self) -> str:
        """
        可视化状态图（文本形式）
        
        Returns:
            状态图的文本表示
        """
        lines = ["Workflow State Graph:", "=" * 50]
        
        for from_state in WorkflowState:
            if from_state in self.transition_map:
                lines.append(f"\n{from_state.value}:")
                for action, to_state in self.transition_map[from_state].items():
                    lines.append(f"  --{action.value}--> {to_state.value}")
        
        lines.append("=" * 50)
        return "\n".join(lines)


# 全局状态图实例
_state_graph = None


def get_state_graph() -> WorkflowStateGraph:
    """
    获取全局状态图实例（单例模式）
    
    Returns:
        状态图实例
    """
    global _state_graph
    if _state_graph is None:
        _state_graph = WorkflowStateGraph()
    return _state_graph
