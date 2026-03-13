from backend.core.prompt_manager import PromptManager


def test_current_runtime_prompt_keys_still_resolve():
    manager = PromptManager(strict=True)

    required_runtime_keys = [
        "router.router_system_prompt",
        "router.router_user_prompt",
        "file_processor.file_processor_system_prompt",
        "file_processor.summary_generation_prompt",
        "generation.generation_system_prompt",
        "generation.generation_with_context_prompt",
        "generation.context_format",
        "generation.answer_quality_prompt",
        "retrieval.query_rewrite_prompt",
        "retrieval.retrieval_summary_prompt",
        "retrieval.retrieval_result_format",
        "retrieval.no_results_prompt",
        "tool.tool_selection_prompt",
        "tool.tool_result_interpretation_prompt",
    ]

    missing_keys = [key for key in required_runtime_keys if not manager.get_prompt(key)]

    assert missing_keys == []
