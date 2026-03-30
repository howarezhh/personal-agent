# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.api.app_services import get_task_runtime_application_service
from backend.api.dependencies import get_current_user_id
from backend.contracts.api.task_runtime import (
    TaskRuntimeActionRequest,
    TaskRuntimeActionResponse,
    TaskRuntimeArtifactResponse,
    TaskRuntimeCheckpointResponse,
    TaskRuntimePrepareResponse,
    TaskRuntimeStatusResponse,
    TaskRuntimeSubmitRequest,
    TaskRuntimeTerminationResponse,
    TaskRuntimeEvaluationReportResponse,
    TaskRuntimeGoalResponse,
    TaskRuntimePlanResponse,
)
from backend.contracts.errors import AppException, ErrorCode, internal_server_error
from backend.contracts.responses import ErrorResponse, SuccessResponse
from backend.utils.logger import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/task-runtime", tags=["task-runtime"])


def _request_id(request: Request, payload_request_id: str | None) -> str | None:
    """优先使用显式 request_id，否则回退到中间件注入的 request_id。"""
    return payload_request_id or getattr(getattr(request, "state", None), "request_id", None)


def _build_not_implemented_response(detail_message: str) -> JSONResponse:
    """为未接入的生命周期接口返回统一 501 响应。"""
    error_payload = ErrorResponse.create(
        code=501,
        message=detail_message,
        error="NotImplemented",
        error_code=ErrorCode.SYSTEM_HTTP_ERROR.value,
    )
    return JSONResponse(status_code=501, content=error_payload.model_dump())


async def _invoke_lifecycle_method(
    service: Any,
    method_name: str,
    **kwargs: Any,
) -> Any | JSONResponse:
    """按名称调用生命周期方法；若实现尚未接入，则返回统一 501 占位响应。"""
    method = getattr(service, method_name, None)
    if not callable(method):
        return _build_not_implemented_response(f"任务生命周期接口 `{method_name}` 尚未接入实现")
    return await method(**kwargs)


@router.post("/tasks", response_model=SuccessResponse[TaskRuntimePrepareResponse])
async def submit_task(
    task_request: TaskRuntimeSubmitRequest,
    http_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    """提交任务并返回初始 goal / plan。"""
    try:
        preparation = await get_task_runtime_application_service().prepare_task(
            user_id=user_id,
            conversation_id=task_request.conversation_id,
            user_input=task_request.user_input,
            message_id=task_request.message_id,
            request_id=_request_id(http_request, task_request.request_id),
            metadata=task_request.metadata,
        )
        return SuccessResponse.create(data=TaskRuntimePrepareResponse.from_preparation(preparation))
    except AppException:
        raise
    except Exception as error:
        logger.error("Task runtime submit failed: %s", error, exc_info=True)
        raise internal_server_error("任务运行时提交失败") from error


@router.post(
    "/tasks/stream",
    responses={
        200: {
            "description": "Task runtime SSE stream",
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                }
            },
        }
    },
)
async def stream_task(
    task_request: TaskRuntimeSubmitRequest,
    http_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    """流式执行任务，并输出统一 SSE 事件流。"""
    task_runtime_service = get_task_runtime_application_service()

    # `/tasks/stream` 仅委托应用服务；若客户端已先调 `/tasks` 会复用缓存，
    # 若未提前 prepare，则由应用服务在首次 stream 时完成同一份预处理。

    stream = task_runtime_service.stream_task_events(
        user_id=user_id,
        conversation_id=task_request.conversation_id,
        user_input=task_request.user_input,
        message_id=task_request.message_id,
        request_id=_request_id(http_request, task_request.request_id),
        metadata=task_request.metadata,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/tasks/{task_id}", response_model=SuccessResponse[TaskRuntimeStatusResponse])
async def get_task_status(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """获取复杂任务的统一状态快照。"""
    task_runtime_service = get_task_runtime_application_service()
    try:
        result = await _invoke_lifecycle_method(
            task_runtime_service,
            "get_task_status",
            user_id=user_id,
            task_id=task_id,
        )
        if isinstance(result, JSONResponse):
            return result
        return SuccessResponse.create(
            data=TaskRuntimeStatusResponse(
                task_id=result.record.task_id,
                request_id=result.record.request_id,
                execution_id=result.record.execution_id,
                status=result.record.status,
                checkpoint_id=result.record.checkpoint_id,
                current_plan_id=result.record.current_plan_id,
                current_step_id=result.record.current_step_id,
                created_at=result.record.created_at,
                updated_at=result.record.updated_at,
                metadata=dict(result.record.metadata),
                goal=TaskRuntimeGoalResponse.from_goal(result.state.goal),
                current_plan=(
                    TaskRuntimePlanResponse.from_plan(result.state.current_plan)
                    if result.state.current_plan is not None
                    else None
                ),
                termination=(
                    TaskRuntimeTerminationResponse.from_termination(result.state.termination)
                    if result.state.termination is not None
                    else None
                ),
                latest_checkpoint=(
                    TaskRuntimeCheckpointResponse.from_checkpoint(result.latest_checkpoint)
                    if result.latest_checkpoint is not None
                    else None
                ),
                artifacts=[TaskRuntimeArtifactResponse.from_artifact(artifact) for artifact in result.state.artifacts],
                evaluation_report=(
                    TaskRuntimeEvaluationReportResponse.from_report(result.state.evaluation_report)
                    if result.state.evaluation_report is not None
                    else None
                ),
            )
        )
    except AppException:
        raise
    except Exception as error:
        logger.error("Get task runtime status failed: %s", error, exc_info=True)
        raise internal_server_error("任务运行时状态查询失败") from error


async def _handle_task_action(
    *,
    task_id: str,
    action: str,
    action_request: TaskRuntimeActionRequest,
    user_id: str,
) -> SuccessResponse[TaskRuntimeActionResponse] | JSONResponse:
    """统一处理 pause / resume / cancel / retry 之类的生命周期动作接口。"""
    task_runtime_service = get_task_runtime_application_service()
    result = await _invoke_lifecycle_method(
        task_runtime_service,
        f"{action}_task",
        user_id=user_id,
        task_id=task_id,
        reason=action_request.reason,
        metadata=action_request.metadata,
    )
    if isinstance(result, JSONResponse):
        return result
    return SuccessResponse.create(
        data=TaskRuntimeActionResponse(
            task_id=result.task_id,
            request_id=result.request_id,
            execution_id=result.execution_id,
            status=result.status,
            checkpoint_id=result.checkpoint_id,
            current_plan_id=result.current_plan_id,
            current_step_id=result.current_step_id,
            created_at=result.created_at,
            updated_at=result.updated_at,
            metadata=dict(result.metadata),
            action=action,
            accepted=True,
            detail_message=f"任务已执行 {action} 动作。",
        )
    )


@router.post(
    "/tasks/{task_id}/stream",
    responses={
        200: {
            "description": "Resume task runtime SSE stream",
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                }
            },
        }
    },
)
async def stream_task_by_id(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """基于持久化检查点继续流式执行任务。"""
    task_runtime_service = get_task_runtime_application_service()
    return StreamingResponse(
        task_runtime_service.stream_task_events_by_task_id(user_id=user_id, task_id=task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/tasks/{task_id}/pause", response_model=SuccessResponse[TaskRuntimeActionResponse])
async def pause_task(
    task_id: str,
    action_request: TaskRuntimeActionRequest,
    user_id: str = Depends(get_current_user_id),
):
    """暂停任务执行。"""
    return await _handle_task_action(
        task_id=task_id,
        action="pause",
        action_request=action_request,
        user_id=user_id,
    )


@router.post("/tasks/{task_id}/resume", response_model=SuccessResponse[TaskRuntimeActionResponse])
async def resume_task(
    task_id: str,
    action_request: TaskRuntimeActionRequest,
    user_id: str = Depends(get_current_user_id),
):
    """恢复已暂停任务。"""
    return await _handle_task_action(
        task_id=task_id,
        action="resume",
        action_request=action_request,
        user_id=user_id,
    )


@router.post("/tasks/{task_id}/cancel", response_model=SuccessResponse[TaskRuntimeActionResponse])
async def cancel_task(
    task_id: str,
    action_request: TaskRuntimeActionRequest,
    user_id: str = Depends(get_current_user_id),
):
    """取消任务执行。"""
    return await _handle_task_action(
        task_id=task_id,
        action="cancel",
        action_request=action_request,
        user_id=user_id,
    )


@router.post("/tasks/{task_id}/retry", response_model=SuccessResponse[TaskRuntimeActionResponse])
async def retry_task(
    task_id: str,
    action_request: TaskRuntimeActionRequest,
    user_id: str = Depends(get_current_user_id),
):
    """重试任务执行。"""
    return await _handle_task_action(
        task_id=task_id,
        action="retry",
        action_request=action_request,
        user_id=user_id,
    )
