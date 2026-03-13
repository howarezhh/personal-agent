from backend.agents.registry import get_agent_registry
from backend.file_processors.parsers.parser_registry import get_parser_registry


def test_agent_registry_exposes_default_agent_types():
    registry = get_agent_registry()
    registered = registry.registered_types()
    assert "router" in registered
    assert "retrieval" in registered
    assert "generation" in registered
    assert "tool" in registered
    assert "file_processor" in registered


def test_parser_registry_exposes_default_parser_types():
    registry = get_parser_registry()
    available = registry.all()
    assert "pdf" in available
    assert "word" in available
    assert "excel" in available
    assert "text" in available
