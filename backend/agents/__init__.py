
from importlib import import_module
from typing import Any

_EXPORTS = {
    "RetrievalAgent": "backend.agents.retrieval",
    "GenerationAgent": "backend.agents.generation",
    "ToolAgent": "backend.agents.tool",
    "FileProcessorAgent": "backend.agents.file_processor.file_processor_agent",
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

    module = import_module(_EXPORTS[name])
    return getattr(module, name)

