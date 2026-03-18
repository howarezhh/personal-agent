# -*- coding: utf-8 -*-


from typing import Callable, Optional
"""
Agent 注册表模块，负责集中注册和实例化各类 Agent。
"""


from backend.agents.base.base_agent import BaseAgent
from backend.agents.file_processor.file_processor_agent import FileProcessorAgent
from backend.agents.generation.generation_agent import GenerationAgent
from backend.agents.retrieval.retrieval_agent import RetrievalAgent
from backend.agents.router.router_agent import RouterAgent
from backend.agents.tool.tool_agent import ToolAgent


AgentFactory = Callable[[], BaseAgent]


class AgentRegistry:
    """
    agen\1\2egistry相关类，用于承载当前模块的核心能力。
    """
    def __init__(self):
        """
        初始化当前对象，并准备执行所需的依赖与状态。
        
        返回：
            返回当前逻辑生成的结果。
        """
        self._factories: dict[str, AgentFactory] = {}

    def register(self, agent_type: str, factory: AgentFactory):
        """
        注册当前业务，并返回对应的处理结果。
        
        参数：
            agent_type: 与“Agent类型”相关的输入参数。
            factory: 与“factory”相关的输入参数。
        
        返回：
            返回当前逻辑生成的结果。
        """
        self._factories[agent_type] = factory

    def create(self, agent_type: str) -> Optional[BaseAgent]:
        """
        创建当前业务，并返回对应的处理结果。
        
        参数：
            agent_type: 与“Agent类型”相关的输入参数。
        
        返回：
            返回 `Optional[BaseAgent]` 类型的结果。
        """
        factory = self._factories.get(agent_type)
        return factory() if factory else None

    def registered_types(self) -> list[str]:
        """
        处理types，并返回对应的处理结果。
        
        返回：
            返回 `list[str]` 类型的结果。
        """
        return sorted(self._factories.keys())


_agent_registry: AgentRegistry | None = None


def get_agent_registry() -> AgentRegistry:
    """
    获取Agentregistry，并返回对应的处理结果。
    
    返回：
        返回 `AgentRegistry` 类型的结果。
    """
    global _agent_registry
    if _agent_registry is None:
        _agent_registry = AgentRegistry()
        register_default_agents(_agent_registry)
    return _agent_registry


def register_default_agents(registry: AgentRegistry | None = None) -> AgentRegistry:
    """
    注册defaultagents，并返回对应的处理结果。
    
    参数：
        registry: 与“registry”相关的输入参数。
    
    返回：
        返回 `AgentRegistry` 类型的结果。
    """
    registry = registry or get_agent_registry()
    registry.register("router", RouterAgent)
    registry.register("retrieval", RetrievalAgent)
    registry.register("generation", GenerationAgent)
    registry.register("tool", ToolAgent)
    registry.register("file_processor", FileProcessorAgent)
    return registry
