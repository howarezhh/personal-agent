"""Agent registry for extensible agent resolution."""

from typing import Callable, Optional

from backend.agents.base.base_agent import BaseAgent
from backend.agents.file_processor.file_processor_agent import FileProcessorAgent
from backend.agents.generation.generation_agent import GenerationAgent
from backend.agents.retrieval.retrieval_agent import RetrievalAgent
from backend.agents.router.router_agent import RouterAgent
from backend.agents.tool.tool_agent import ToolAgent


AgentFactory = Callable[[], BaseAgent]


class AgentRegistry:
    def __init__(self):
        self._factories: dict[str, AgentFactory] = {}

    def register(self, agent_type: str, factory: AgentFactory):
        self._factories[agent_type] = factory

    def create(self, agent_type: str) -> Optional[BaseAgent]:
        factory = self._factories.get(agent_type)
        return factory() if factory else None

    def registered_types(self) -> list[str]:
        return sorted(self._factories.keys())


_agent_registry: AgentRegistry | None = None


def get_agent_registry() -> AgentRegistry:
    global _agent_registry
    if _agent_registry is None:
        _agent_registry = AgentRegistry()
        register_default_agents(_agent_registry)
    return _agent_registry


def register_default_agents(registry: AgentRegistry | None = None) -> AgentRegistry:
    registry = registry or get_agent_registry()
    registry.register("router", RouterAgent)
    registry.register("retrieval", RetrievalAgent)
    registry.register("generation", GenerationAgent)
    registry.register("tool", ToolAgent)
    registry.register("file_processor", FileProcessorAgent)
    return registry
