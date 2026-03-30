# -*- coding: utf-8 -*-
"""PromptManager 模板工厂回归测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

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
input_variables:
  - question
  - name
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
    用户问题：{question}
  generation_custom_prompt: |
    你好，{name}！
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


def test_render_prompt_fails_fast_when_required_variables_missing(tmp_path: Path) -> None:
    """渲染缺参时应直接失败，而不是返回原始模板。"""
    _write_prompt_file(tmp_path)
    manager = PromptManager(prompts_dir=tmp_path)

    with pytest.raises(ValueError, match="generation.generation_custom_prompt"):
        manager.render_prompt("generation.generation_custom_prompt")


def test_build_chat_prompt_call_preserves_real_history_messages(tmp_path: Path) -> None:
    """ChatPromptTemplate 调用参数应保留真实历史消息，而不是先字符串化。"""
    _write_prompt_file(tmp_path)
    manager = PromptManager(prompts_dir=tmp_path)

    prompt_template, prompt_variables = manager.build_chat_prompt_call(
        user_prompt_key="generation.generation_user_prompt",
        user_variables={"question": "现在几点？"},
        system_prompt_key="generation.generation_system_prompt",
        conversation_history=[{"role": "user", "content": "你好"}],
    )

    prompt_value = prompt_template.invoke(prompt_variables)
    messages = prompt_value.to_messages()

    assert messages[0].type == "system"
    assert messages[1].type == "human"
    assert messages[1].content == "你好"
    assert messages[2].type == "human"
    assert "现在几点？" in messages[2].content
