
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.dependencies import get_current_user_id
from backend.api.models import MessageResponse, PaginatedResponse, SuccessResponse
from backend.application.services import ConversationApplicationService
from backend.database.repositories.conversation_repository import get_conversation_repository
from backend.database.repositories.message_repository import get_message_repository
from backend.infrastructure.persistence import ConversationRepositoryAdapter, MessageRepositoryAdapter
from backend.utils.logger import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


def get_conversation_application_service() -> ConversationApplicationService:
    return ConversationApplicationService(
        conversation_repo=ConversationRepositoryAdapter(repository=get_conversation_repository()),
        message_repo=MessageRepositoryAdapter(repository=get_message_repository()),
    )


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


class CreateConversationRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200, description="会话标题")
    description: Optional[str] = Field(default=None, max_length=500, description="会话描述")


class UpdateConversationRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200, description="会话标题")
    description: Optional[str] = Field(default=None, max_length=500, description="会话描述")


def _iso(value) -> str:
    return value.isoformat() if value else ""


def _serialize_conversation(conversation) -> ConversationResponse:
    return ConversationResponse(
        conversation_id=conversation.conversation_id,
        user_id=conversation.user_id,
        title=conversation.title,
        description=conversation.description,
        message_count=conversation.message_count,
        is_active=conversation.is_active,
        created_at=_iso(conversation.created_at),
        updated_at=_iso(conversation.updated_at),
    )


def _serialize_summary(summary) -> ConversationSummaryResponse:
    return ConversationSummaryResponse(
        conversation_id=summary.conversation_id,
        title=summary.title,
        message_count=summary.message_count,
        last_message_preview=summary.last_message_preview,
        updated_at=_iso(summary.updated_at),
    )


def _serialize_message(message) -> ConversationMessageItem:
    return ConversationMessageItem(
        message_id=message.message_id,
        conversation_id=message.conversation_id,
        message_type=message.message_type,
        content=message.content,
        sequence_number=message.sequence_number,
        parent_message_id=message.parent_message_id,
        created_at=_iso(message.created_at),
    )


@router.get("", response_model=PaginatedResponse[ConversationSummaryResponse])
async def get_conversations(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
    only_active: bool = Query(default=True, description="是否只返回激活会话"),
    user_id: str = Depends(get_current_user_id),
):
    try:
        summaries, total = get_conversation_application_service().list_conversations(
            user_id=user_id,
            page=page,
            page_size=page_size,
            only_active=only_active,
        )
        return PaginatedResponse.create(
            data=[_serialize_summary(summary) for summary in summaries],
            total=total,
            page=page,
            page_size=page_size,
        )
    except Exception as error:
        logger.error("Failed to list conversations: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取会话列表失败")


@router.get("/{conversation_id}", response_model=SuccessResponse[ConversationResponse])
async def get_conversation(conversation_id: str, user_id: str = Depends(get_current_user_id)):
    try:
        conversation = get_conversation_application_service().get_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if not conversation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在或无权访问")
        return SuccessResponse.create(data=_serialize_conversation(conversation))
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Failed to get conversation: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取会话详情失败")


@router.get("/{conversation_id}/messages", response_model=PaginatedResponse[ConversationMessageItem])
async def get_conversation_messages(
    conversation_id: str,
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=50, ge=1, le=200, description="每页大小"),
    user_id: str = Depends(get_current_user_id),
):
    try:
        total, messages = get_conversation_application_service().get_messages(
            user_id=user_id,
            conversation_id=conversation_id,
            page=page,
            page_size=page_size,
        )
        if total is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在或无权访问")
        return PaginatedResponse.create(
            data=[_serialize_message(message) for message in messages],
            total=total,
            page=page,
            page_size=page_size,
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Failed to get conversation messages: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取消息列表失败")


@router.post("", response_model=SuccessResponse[ConversationResponse], status_code=status.HTTP_201_CREATED)
async def create_conversation(request: CreateConversationRequest, user_id: str = Depends(get_current_user_id)):
    try:
        conversation = get_conversation_application_service().create_conversation(
            user_id=user_id,
            title=request.title,
            description=request.description,
        )
        return SuccessResponse.create(data=_serialize_conversation(conversation), message="Conversation created successfully")
    except Exception as error:
        logger.error("Failed to create conversation: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="创建会话失败")


@router.put("/{conversation_id}", response_model=SuccessResponse[ConversationResponse])
async def update_conversation(
    conversation_id: str,
    request: UpdateConversationRequest,
    user_id: str = Depends(get_current_user_id),
):
    try:
        conversation = get_conversation_application_service().update_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
            title=request.title,
            description=request.description,
        )
        if not conversation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在或无权访问")
        return SuccessResponse.create(data=_serialize_conversation(conversation), message="Conversation updated successfully")
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Failed to update conversation: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新会话失败")


@router.delete("/{conversation_id}", response_model=MessageResponse)
async def delete_conversation(conversation_id: str, user_id: str = Depends(get_current_user_id)):
    try:
        deleted = get_conversation_application_service().delete_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在或无权访问")
        return MessageResponse.create(message="Conversation deleted successfully")
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Failed to delete conversation: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除会话失败")
