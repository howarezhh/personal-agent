# -*- coding: utf-8 -*-

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from backend.api.app_services import get_conversation_application_service
from backend.api.dependencies import get_current_user_id
from backend.contracts.api.conversations import (
    ConversationMessageItem,
    ConversationResponse,
    ConversationSummaryResponse,
    CreateConversationRequest,
    UpdateConversationRequest,
)
from backend.contracts.errors import ErrorCode, internal_server_error, not_found
from backend.contracts.responses import MessageResponse, PaginatedResponse, SuccessResponse
from backend.utils.logger import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


CONVERSATION_NOT_FOUND_MESSAGE = "会话不存在或无权访问"


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
    # 历史消息接口必须返回完整消息对象，确保刷新后仍能还原引用和链路字段。
    return ConversationMessageItem(
        message_id=message.message_id,
        conversation_id=message.conversation_id,
        message_type=message.message_type,
        content=message.content,
        sequence_number=message.sequence_number,
        parent_message_id=message.parent_message_id,
        created_at=_iso(message.created_at),
        metadata=dict(message.metadata or {}),
    )


def _conversation_not_found() -> Exception:
    return not_found(
        CONVERSATION_NOT_FOUND_MESSAGE,
        error_code=ErrorCode.CONVERSATION_NOT_FOUND,
        error="ConversationNotFound",
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
        if getattr(error, "status_code", None):
            raise
        logger.error("Failed to list conversations: %s", error, exc_info=True)
        raise internal_server_error("获取会话列表失败") from error


@router.get("/{conversation_id}", response_model=SuccessResponse[ConversationResponse])
async def get_conversation(conversation_id: str, user_id: str = Depends(get_current_user_id)):
    try:
        conversation = get_conversation_application_service().get_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if not conversation:
            raise _conversation_not_found()
        return SuccessResponse.create(data=_serialize_conversation(conversation))
    except Exception as error:
        if getattr(error, "status_code", None):
            raise
        logger.error("Failed to get conversation: %s", error, exc_info=True)
        raise internal_server_error("获取会话详情失败") from error


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
            raise _conversation_not_found()
        return PaginatedResponse.create(
            data=[_serialize_message(message) for message in messages],
            total=total,
            page=page,
            page_size=page_size,
        )
    except Exception as error:
        if getattr(error, "status_code", None):
            raise
        logger.error("Failed to get conversation messages: %s", error, exc_info=True)
        raise internal_server_error("获取消息列表失败") from error


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
        if getattr(error, "status_code", None):
            raise
        logger.error("Failed to create conversation: %s", error, exc_info=True)
        raise internal_server_error("创建会话失败") from error


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
            raise _conversation_not_found()
        return SuccessResponse.create(data=_serialize_conversation(conversation), message="Conversation updated successfully")
    except Exception as error:
        if getattr(error, "status_code", None):
            raise
        logger.error("Failed to update conversation: %s", error, exc_info=True)
        raise internal_server_error("更新会话失败") from error


@router.delete("/{conversation_id}", response_model=MessageResponse)
async def delete_conversation(conversation_id: str, user_id: str = Depends(get_current_user_id)):
    try:
        deleted = get_conversation_application_service().delete_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if not deleted:
            raise _conversation_not_found()
        return MessageResponse.create(message="Conversation deleted successfully")
    except Exception as error:
        if getattr(error, "status_code", None):
            raise
        logger.error("Failed to delete conversation: %s", error, exc_info=True)
        raise internal_server_error("删除会话失败") from error
