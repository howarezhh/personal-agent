# -*- coding: utf-8 -*-
"""LangChain 模型交互层回归测试。"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field

from backend.core.llm_manager import LangChainModelManager, LangChainModelRuntime


class FakeModelRuntime(LangChainModelRuntime):
    """用于测试的假模型运行时。"""

    def __init__(self, *, response: str = "", stream_chunks: List[str] | None = None):
        self.response = response
        self.stream_chunks = stream_chunks or []
        self.calls: List[Dict[str, Any]] = []

    async def invoke(self, messages: List[Dict[str, str]], options) -> str:  # type: ignore[override]
        self.calls.append({"method": "invoke", "messages": messages, "options": options})
        return self.response

    async def stream(self, messages: List[Dict[str, str]], options):  # type: ignore[override]
        self.calls.append({"method": "stream", "messages": messages, "options": options})
        for chunk in self.stream_chunks:
            yield chunk


class DemoStructuredResult(BaseModel):
    """测试用结构化结果。"""

    answer: str
    confidence: float = 0.0


class ToolSelectionResult(BaseModel):
    """测试用工具选择结果。"""

    tool_name: str | None = None
    tool_params: Dict[str, Any] = Field(default_factory=dict)


@pytest.mark.asyncio
async def test_invoke_messages_keeps_existing_message_contract() -> None:
    """消息调用应保持项目内部消息结构不变。"""
    runtime = FakeModelRuntime(response="ok")
    manager = LangChainModelManager(runtime=runtime)

    result = await manager.invoke_messages(
        messages=[
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "用户问题"},
        ],
        temperature=0.2,
        max_tokens=128,
    )

    assert result == "ok"
    assert runtime.calls[0]["messages"] == [
        {"role": "system", "content": "系统提示"},
        {"role": "user", "content": "用户问题"},
    ]
    assert runtime.calls[0]["options"].temperature == 0.2
    assert runtime.calls[0]["options"].max_tokens == 128


@pytest.mark.asyncio
async def test_with_structured_output_parses_json_payload() -> None:
    """结构化输出应由模型交互层负责解析与校验。"""
    runtime = FakeModelRuntime(response='```json\n{"answer": "done", "confidence": 0.91}\n```')
    manager = LangChainModelManager(runtime=runtime).with_structured_output(DemoStructuredResult)

    result = await manager.invoke_prompt_template(
        PromptTemplate.from_template("请返回结构化结果：{question}"),
        {"question": "测试"},
    )

    assert isinstance(result, DemoStructuredResult)
    assert result.answer == "done"
    assert result.confidence == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_bind_tools_injects_tool_instruction_before_model_call() -> None:
    """工具绑定不能把工具私有结构散落到业务层。"""
    runtime = FakeModelRuntime(response='{"tool_name": "translation", "tool_params": {"target_lang": "en"}}')
    manager = (
        LangChainModelManager(runtime=runtime)
        .bind_tools(
            [
                {
                    "name": "translation",
                    "description": "翻译工具",
                    "input_schema": {"type": "object", "properties": {"target_lang": {"type": "string"}}},
                }
            ]
        )
        .with_structured_output(ToolSelectionResult)
    )

    result = await manager.invoke_messages(messages=[{"role": "user", "content": "把这句话翻成英文"}])

    assert isinstance(result, ToolSelectionResult)
    assert result.tool_name == "translation"
    assert runtime.calls[0]["messages"][0]["role"] == "system"
    assert "translation" in runtime.calls[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_invoke_prompt_template_formats_variables_before_model_call() -> None:
    """模板调用应先完成变量渲染，再传入统一消息契约。"""
    runtime = FakeModelRuntime(response="ok")
    manager = LangChainModelManager(runtime=runtime)

    result = await manager.invoke_prompt_template(
        PromptTemplate.from_template("你好，{name}"),
        {"name": "小明"},
        system_prompt="你是助手",
    )

    assert result == "ok"
    assert runtime.calls[0]["messages"] == [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "你好，小明"},
    ]


@pytest.mark.asyncio
async def test_stream_prompt_template_only_returns_plain_text_chunks() -> None:
    """模板流式调用也只能暴露纯文本分片。"""
    runtime = FakeModelRuntime(stream_chunks=["你好", "，", "世界"])
    manager = LangChainModelManager(runtime=runtime)

    collected: List[str] = []
    async for chunk in manager.stream_prompt_template(
        PromptTemplate.from_template("请向 {target} 问好"),
        {"target": "世界"},
    ):
        collected.append(chunk)

    assert collected == ["你好", "，", "世界"]
    assert runtime.calls[0]["method"] == "stream"
    assert runtime.calls[0]["messages"] == [{"role": "user", "content": "请向 世界 问好"}]
    assert all(isinstance(chunk, str) for chunk in collected)
