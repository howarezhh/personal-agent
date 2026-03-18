from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=5000, description="用户问题")
    conversation_id: Optional[str] = Field(None, description="会话ID，可空")
    stream: bool = Field(default=True, description="是否使用流式输出")
    enable_knowledge_base: bool = Field(default=False, description="是否启用知识库增强")
    knowledge_base_id: Optional[str] = Field(default=None, description="知识库 ID")


class PauseRequest(BaseModel):
    stream_id: str = Field(..., min_length=1, description="流式会话 ID")


class PauseStreamResponse(BaseModel):
    stream_id: str = Field(..., description="流式会话 ID")
    paused: bool = Field(..., description="是否已暂停")


class AskResponse(BaseModel):
    conversation_id: str = Field(..., description="会话 ID")
    message_id: str = Field(..., description="消息 ID")
    answer: str = Field(..., description="回答内容")
    execution_id: Optional[str] = Field(None, description="执行 ID")
    citations: list[Dict[str, Any]] = Field(default_factory=list, description="引用列表")


class ChatResultPayload(BaseModel):
    status: Optional[str] = Field(default=None, description="工作流或结果状态")
    final_step_key: Optional[str] = Field(default=None, description="最终步骤标识")
    final_content: Optional[str] = Field(default=None, description="最终文本内容")
    step_count: Optional[int] = Field(default=None, description="步骤数量")
    execution_id: Optional[str] = Field(default=None, description="执行 ID")
    citations: list[Dict[str, Any]] = Field(default_factory=list, description="引用列表")
    route_decision: Optional[Dict[str, Any]] = Field(default=None, description="路由决策")
    retrieval_results: list[Dict[str, Any]] = Field(default_factory=list, description="检索结果")
    tool_result: Optional[Dict[str, Any]] = Field(default=None, description="工具结果")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="扩展元数据")


class ChatDonePayload(ChatResultPayload):
    conversation_id: Optional[str] = Field(default=None, description="会话 ID")
    assistant_message_id: Optional[str] = Field(default=None, description="助手消息 ID")
