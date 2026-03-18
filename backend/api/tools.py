# -*- coding: utf-8 -*-

from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Depends

from backend.api.app_services import get_tool_application_service
from backend.api.dependencies import get_current_user
from backend.application.services.tool_application_service import (
    ToolAccessDeniedError,
    ToolNotAvailableError,
)
from backend.contracts.api.tools import (
    ToolCategoryInfo,
    ToolCategoryListResponse,
    ToolDetailResponse,
    ToolExecuteRequest,
    ToolExecuteResponse,
    ToolInfo,
    ToolListResponse,
)
from backend.contracts.errors import ErrorCode, forbidden, internal_server_error, not_found
from backend.models.user import User
from backend.utils.logger import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/tools", tags=["tools"])
tool_service = get_tool_application_service()


@router.get(
    "/categories/list",
    response_model=ToolCategoryListResponse,
    summary="List tool categories",
    description="Return categories for tools visible to the current user.",
)
async def get_tool_categories(current_user: User = Depends(get_current_user)):
    try:
        logger.info("User %s requests tool categories", current_user.user_id)
        category_items = [
            ToolCategoryInfo(**item)
            for item in tool_service.list_tool_categories(is_admin=getattr(current_user, "is_admin", False))
        ]
        return ToolCategoryListResponse(success=True, data=category_items, total=len(category_items))
    except Exception as error:
        if getattr(error, "status_code", None):
            raise
        logger.error("Failed to get tool categories: %s", error, exc_info=True)
        raise internal_server_error("Failed to list tool categories") from error


@router.get(
    "",
    response_model=ToolListResponse,
    summary="List tools",
    description="Return tools visible to the current user.",
)
async def get_tools_list(category: Optional[str] = None, current_user: User = Depends(get_current_user)):
    try:
        logger.info("User %s requests tools, category=%s", current_user.user_id, category)
        tool_items = [
            ToolInfo(**item)
            for item in tool_service.list_tools(
                is_admin=getattr(current_user, "is_admin", False),
                category=category,
            )
        ]
        return ToolListResponse(success=True, data=tool_items, total=len(tool_items))
    except Exception as error:
        if getattr(error, "status_code", None):
            raise
        logger.error("Failed to get tools list: %s", error, exc_info=True)
        raise internal_server_error("Failed to list tools") from error


@router.get(
    "/{tool_name}",
    response_model=ToolDetailResponse,
    summary="Get tool detail",
    description="Return detail for a tool visible to the current user.",
)
async def get_tool_detail(tool_name: str, current_user: User = Depends(get_current_user)):
    try:
        logger.info("User %s requests tool detail: %s", current_user.user_id, tool_name)
        tool_info = ToolInfo(
            **tool_service.get_tool_detail(
                tool_name=tool_name,
                is_admin=getattr(current_user, "is_admin", False),
            )
        )
        return ToolDetailResponse(success=True, data=tool_info)
    except ToolNotAvailableError as error:
        raise not_found(str(error), error_code=ErrorCode.TOOL_NOT_FOUND, error="ToolNotFound") from error
    except Exception as error:
        if getattr(error, "status_code", None):
            raise
        logger.error("Failed to get tool detail: %s", error, exc_info=True)
        raise internal_server_error("Failed to get tool detail") from error


@router.post(
    "/{tool_name}/execute",
    response_model=ToolExecuteResponse,
    summary="Execute tool",
    description="Execute the specified tool.",
)
async def execute_tool(tool_name: str, request: ToolExecuteRequest, current_user: User = Depends(get_current_user)):
    start_time = time.time()
    try:
        logger.info("User %s executes tool: %s", current_user.user_id, tool_name)
        result = await tool_service.execute_tool(
            tool_name=tool_name,
            parameters=request.parameters,
            user_id=current_user.user_id,
            is_admin=getattr(current_user, "is_admin", False),
            metadata={"source": "tools_api", "user_id": current_user.user_id},
        )
        logger.info(
            "Tool execution completed: tool_name=%s, success=%s, cost_ms=%s",
            tool_name,
            result.get("success"),
            int((time.time() - start_time) * 1000),
        )
        return ToolExecuteResponse(
            success=result.get("success", False),
            data=result.get("data"),
            error=result.get("error"),
            error_code=result.get("error_code"),
            error_type=result.get("error_type"),
            metadata=result.get("metadata"),
        )
    except ToolAccessDeniedError as error:
        raise forbidden(str(error), error_code=ErrorCode.TOOL_ACCESS_DENIED, error="ToolAccessDenied") from error
    except ToolNotAvailableError as error:
        raise not_found(str(error), error_code=ErrorCode.TOOL_NOT_FOUND, error="ToolNotFound") from error
    except Exception as error:
        if getattr(error, "status_code", None):
            raise
        logger.error("Failed to execute tool: %s", error, exc_info=True)
        return ToolExecuteResponse(
            success=False,
            data=None,
            error=f"Tool execution failed: {error}",
            error_code=ErrorCode.SYSTEM_INTERNAL_ERROR.value,
            error_type="execution_error",
            metadata={"tool_name": tool_name},
        )
