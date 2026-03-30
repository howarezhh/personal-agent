from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ConversationResponse(BaseModel):
    conversation_id: str = Field(..., description="会话 ID")
    user_id: str = Field(..., description="用户 ID")
    title: str = Field(..., description="会话标题")
    description: Optional[str] = Field(default=None, description="会话描述")
    message_count: int = Field(default=0, description="消息数量")
    is_active: bool = Field(default=True, description="是否激活")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")


class ConversationSummaryResponse(BaseModel):
    conversation_id: str = Field(..., description="会话 ID")
    title: str = Field(..., description="会话标题")
    message_count: int = Field(default=0, description="消息数量")
    last_message_preview: Optional[str] = Field(default=None, description="最后一条消息预览")
    updated_at: str = Field(..., description="更新时间")


class ConversationMessageItem(BaseModel):
    message_id: str = Field(..., description="消息 ID")
    conversation_id: str = Field(..., description="会话 ID")
    message_type: str = Field(..., description="消息类型")
    content: str = Field(..., description="消息内容")
    sequence_number: int = Field(..., description="序号")
    parent_message_id: Optional[str] = Field(default=None, description="父消息 ID")
    created_at: str = Field(..., description="创建时间")
    metadata: dict[str, Any] = Field(default_factory=dict, description="消息扩展元数据")


class CreateConversationRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200, description="会话标题")
    description: Optional[str] = Field(default=None, max_length=500, description="会话描述")


class UpdateConversationRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200, description="会话标题")
    description: Optional[str] = Field(default=None, max_length=500, description="会话描述")
