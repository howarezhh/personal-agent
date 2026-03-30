# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel

from backend.core.llm_manager import LangChainModelManager, LangChainModelRuntime


class AnswerSchema(BaseModel):
    answer: str


class FakeRunnable:
    def __init__(self, chat_model: "FakeChatModel", mode: str):
        self.chat_model = chat_model
        self.mode = mode

    async def ainvoke(self, messages):
        self.chat_model.runnable_messages = messages
        if self.mode == "structured":
            if self.chat_model.structured_error is not None:
                raise self.chat_model.structured_error
            return self.chat_model.structured_result
        return self.chat_model.bound_result


class FakeChatModel:
    def __init__(self):
        self.last_messages = None
        self.runnable_messages = None
        self.stream_messages = None
        self.bound_tools = None
        self.structured_schema = None
        self.structured_error = None
        self.plain_result = AIMessage(content="plain response")
        self.bound_result = AIMessage(
            content="",
            tool_calls=[{"name": "weather", "args": {"city": "Shanghai"}, "id": "call_1", "type": "tool_call"}],
        )
        self.structured_result = AnswerSchema(answer="structured response")
        self.stream_result = [AIMessageChunk(content="hello"), AIMessageChunk(content=" world")]

    async def ainvoke(self, messages):
        self.last_messages = messages
        return self.plain_result

    async def astream(self, messages):
        self.stream_messages = messages
        for chunk in self.stream_result:
            yield chunk

    def bind_tools(self, tools):
        self.bound_tools = tools
        return FakeRunnable(self, "bound")

    def with_structured_output(self, schema):
        self.structured_schema = schema
        return FakeRunnable(self, "structured")


class FakeRuntime:
    def __init__(self, chat_model: FakeChatModel):
        self.chat_model = chat_model
        self.options = []

    def get_langchain_chat_model(self, *, options=None):
        self.options.append(options)
        return self.chat_model


@pytest.mark.asyncio
async def test_invoke_messages_returns_plain_text_from_native_chat_model() -> None:
    chat_model = FakeChatModel()
    manager = LangChainModelManager(runtime=FakeRuntime(chat_model))

    result = await manager.invoke_messages([{"role": "user", "content": "hello"}])

    assert result == "plain response"
    assert isinstance(chat_model.last_messages[0], HumanMessage)
    assert chat_model.last_messages[0].content == "hello"


@pytest.mark.asyncio
async def test_with_structured_output_uses_native_langchain_schema() -> None:
    chat_model = FakeChatModel()
    manager = LangChainModelManager(runtime=FakeRuntime(chat_model))

    result = await manager.with_structured_output(AnswerSchema).invoke_messages(
        [{"role": "user", "content": "Return structured data"}]
    )

    assert isinstance(result, AnswerSchema)
    assert result.answer == "structured response"
    assert chat_model.structured_schema is AnswerSchema


@pytest.mark.asyncio
async def test_with_structured_output_falls_back_to_json_parsing_when_native_call_fails() -> None:
    chat_model = FakeChatModel()
    chat_model.structured_error = ValueError("Error code: 400, with error text {\"error\":{\"code\":\"1210\"}}")
    chat_model.plain_result = AIMessage(content='{"answer": "fallback response"}')
    manager = LangChainModelManager(runtime=FakeRuntime(chat_model))

    result = await manager.with_structured_output(AnswerSchema).invoke_messages(
        [{"role": "user", "content": "Return structured data"}]
    )

    assert isinstance(result, AnswerSchema)
    assert result.answer == "fallback response"
    assert isinstance(chat_model.last_messages[0], SystemMessage)


@pytest.mark.asyncio
async def test_bind_tools_uses_native_langchain_bind_tools() -> None:
    chat_model = FakeChatModel()
    manager = LangChainModelManager(runtime=FakeRuntime(chat_model))
    tools = [SimpleNamespace(name="weather")]

    result = await manager.bind_tools(tools).invoke_messages([{"role": "user", "content": "check weather"}])

    assert isinstance(result, AIMessage)
    assert chat_model.bound_tools == tools
    assert result.tool_calls[0]["name"] == "weather"


@pytest.mark.asyncio
async def test_bind_tools_and_structured_output_conflict_raises_immediately() -> None:
    chat_model = FakeChatModel()
    manager = LangChainModelManager(runtime=FakeRuntime(chat_model))

    with pytest.raises(ValueError, match=r"bind_tools\(\).*with_structured_output\(\)"):
        await manager.bind_tools([SimpleNamespace(name="weather")]).with_structured_output(AnswerSchema).invoke_messages(
            [{"role": "user", "content": "bad combination"}]
        )


@pytest.mark.asyncio
async def test_invoke_messages_preserves_tool_protocol_fields() -> None:
    chat_model = FakeChatModel()
    manager = LangChainModelManager(runtime=FakeRuntime(chat_model))

    await manager.invoke_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"name": "weather", "args": {"city": "Shanghai"}, "id": "call_1", "type": "tool_call"}
                ],
            },
            {
                "role": "tool",
                "content": '{"success": true}',
                "tool_call_id": "call_1",
                "name": "weather",
                "status": "success",
            },
        ]
    )

    received_messages = chat_model.last_messages
    assert isinstance(received_messages[0], AIMessage)
    assert received_messages[0].tool_calls[0]["id"] == "call_1"
    assert received_messages[0].tool_calls[0]["name"] == "weather"
    assert isinstance(received_messages[1], ToolMessage)
    assert received_messages[1].tool_call_id == "call_1"
    assert received_messages[1].name == "weather"


@pytest.mark.asyncio
async def test_stream_messages_uses_native_langchain_astream() -> None:
    chat_model = FakeChatModel()
    manager = LangChainModelManager(runtime=FakeRuntime(chat_model))

    chunks = []
    async for chunk in manager.stream_messages([{"role": "user", "content": "stream please"}]):
        chunks.append(chunk)

    assert "".join(chunks) == "hello world"
    assert isinstance(chat_model.stream_messages[0], HumanMessage)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("manager_factory", "expected_message"),
    [
        (
            lambda manager: manager.bind_tools([SimpleNamespace(name="weather")]),
            "当前结构化输出/工具绑定链路仅支持非流式调用",
        ),
        (
            lambda manager: manager.with_structured_output(AnswerSchema),
            "当前结构化输出/工具绑定链路仅支持非流式调用",
        ),
    ],
)
async def test_stream_messages_rejects_bound_tools_and_structured_output(manager_factory, expected_message) -> None:
    chat_model = FakeChatModel()
    manager = manager_factory(LangChainModelManager(runtime=FakeRuntime(chat_model)))

    with pytest.raises(ValueError, match=expected_message):
        async for _chunk in manager.stream_messages([{"role": "user", "content": "stream please"}]):
            pass


def test_serialize_langchain_messages_uses_provider_tool_format() -> None:
    runtime = LangChainModelRuntime.__new__(LangChainModelRuntime)
    serialized = runtime.serialize_langchain_messages(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "weather", "args": {"city": "Shanghai"}, "id": "call_1", "type": "tool_call"}
                ],
            ),
            ToolMessage(content='{"success": true}', tool_call_id="call_1", name="weather", status="success"),
        ]
    )

    assert serialized[0]["role"] == "assistant"
    assert serialized[0]["tool_calls"][0]["type"] == "function"
    assert serialized[0]["tool_calls"][0]["function"]["name"] == "weather"
    assert serialized[1]["role"] == "tool"
    assert serialized[1]["tool_call_id"] == "call_1"


@pytest.mark.asyncio
async def test_openai_stream_uses_background_thread_bridge() -> None:
    runtime = LangChainModelRuntime.__new__(LangChainModelRuntime)
    runtime.model_name = "gpt-test"
    runtime.model_config = {"temperature": 0.7, "max_tokens": 128, "top_p": 0.9}

    worker_thread_ids: list[int] = []

    def _stream_factory(**kwargs):
        class _Chunk:
            def __init__(self, content: str):
                self.choices = [SimpleNamespace(delta=SimpleNamespace(content=content))]

        def _iterator():
            worker_thread_ids.append(threading.get_ident())
            yield _Chunk("hello")
            worker_thread_ids.append(threading.get_ident())
            yield _Chunk(" world")

        return _iterator()

    runtime.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_stream_factory)))

    options = SimpleNamespace(model=None, temperature=None, max_tokens=None, top_p=None, extra_kwargs={})
    chunks = []
    async for chunk in runtime._stream_openai([{"role": "user", "content": "hi"}], options):
        chunks.append(chunk)

    assert "".join(chunks) == "hello world"
    assert worker_thread_ids
    assert all(thread_id != threading.get_ident() for thread_id in worker_thread_ids)
