# -*- coding: utf-8 -*-
"""PromptManager 模板工厂回归测试。"""

from __future__ import annotations

from pathlib import Path

from backend.core.prompt_manager import PromptManager


def _write_prompt_file(base_dir: Path) -> None:
    """写入最小可用 Prompt 文档。"""
    prompt_file = base_dir / "generation" / "generation_runtime_v1.yaml"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(
        """
name: Runtime prompts for generation agent
version: v1
agent: generation
scene: runtime_defaults
input_variables: []
output_requirements: []
applicable_models: []
change_log:
  - version: v1
    date: '2026-03-18'
    summary: test prompt
prompts:
  generation_system_prompt: |
    你是测试系统提示词。
  generation_user_prompt: |
    对话历史：{conversation_history}
    用户问题：{question}
  generation_custom_prompt: |
    你好，{name}！
  conversation_history_format: |
    {role}: {content}
  no_history_placeholder: |
    （无历史）
""".strip(),
        encoding="utf-8",
    )


def test_get_prompt_template_renders_from_prompt_source(tmp_path: Path) -> None:
    """普通 Prompt 模板必须来自 Prompt 文件，而不是代码硬编码。"""
    _write_prompt_file(tmp_path)
    manager = PromptManager(prompts_dir=tmp_path)

    prompt_template = manager.get_prompt_template("generation.generation_custom_prompt")
    rendered = prompt_template.invoke({"name": "LangChain"}).to_string()

    assert rendered.strip() == "你好，LangChain！"


def test_build_chat_prompt_template_uses_agent_default_keys(tmp_path: Path) -> None:
    """ChatPromptTemplate 应按 agent 默认键装配 system/user 模板。"""
    _write_prompt_file(tmp_path)
    manager = PromptManager(prompts_dir=tmp_path)

    chat_prompt_template = manager.build_chat_prompt_template("generation")
    prompt_value = chat_prompt_template.invoke(
        {
            "question": "测试问题",
            "conversation_history": "user: 你好",
        }
    )
    messages = prompt_value.to_messages()

    assert messages[0].content == "你是测试系统提示词。\n"
    assert "测试问题" in messages[1].content
    assert "user: 你好" in messages[1].content


def test_build_chat_messages_keeps_project_internal_message_contract(tmp_path: Path) -> None:
    """新消息构造入口应输出项目内部稳定的 message 数组。"""
    _write_prompt_file(tmp_path)
    manager = PromptManager(prompts_dir=tmp_path)

    messages = manager.build_chat_messages(
        agent_type="generation",
        user_content="现在几点？",
        conversation_history=[{"role": "user", "content": "你好"}],
    )

    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "现在几点？" in messages[1]["content"]
    assert "user: 你好" in messages[1]["content"]
