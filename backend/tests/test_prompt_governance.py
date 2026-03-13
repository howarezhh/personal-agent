from backend.core.prompt_manager import PromptManager


def test_versioned_prompt_documents_validate_cleanly():
    manager = PromptManager(strict=True)
    assert manager.validate_versioned_prompts() == []


def test_versioned_prompt_metadata_and_keys_are_available():
    manager = PromptManager(strict=True)

    router_metadata = manager.get_prompt_metadata("router", "classification")
    assert router_metadata["version"] == "v1"
    assert router_metadata["agent"] == "router"

    assert manager.get_prompt("tool.content_optimizer_polish_prompt")
    assert manager.get_prompt("tool.translation_prompt")
    assert manager.get_prompt("tool.database_query_sql_generation_prompt")
    assert manager.get_prompt("tool.novel_generator_outline_prompt")
    assert manager.get_prompt("tool.script_generator_outline_prompt")
    assert manager.get_prompt("generation.creative_writing_request_analysis_prompt")
