from __future__ import annotations

from enum import StrEnum


class AsyncTaskStatus(StrEnum):
    """统一异步任务状态机。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


_LEGACY_ASYNC_TASK_STATUS_MAPPING = {
    "processing": AsyncTaskStatus.RUNNING.value,
    "running": AsyncTaskStatus.RUNNING.value,
    "retrying": AsyncTaskStatus.RUNNING.value,
    "completed": AsyncTaskStatus.SUCCEEDED.value,
    "success": AsyncTaskStatus.SUCCEEDED.value,
    "succeeded": AsyncTaskStatus.SUCCEEDED.value,
    "timeout": AsyncTaskStatus.TIMED_OUT.value,
    "timed_out": AsyncTaskStatus.TIMED_OUT.value,
    "cancelled": AsyncTaskStatus.CANCELLED.value,
    "failed": AsyncTaskStatus.FAILED.value,
    "pending": AsyncTaskStatus.PENDING.value,
    "not_started": AsyncTaskStatus.PENDING.value,
    "queued": AsyncTaskStatus.PENDING.value,
}


def normalize_async_task_status(value: str | None, default: AsyncTaskStatus = AsyncTaskStatus.PENDING) -> str:
    """把历史状态和值域外状态归一到统一任务状态机。"""

    if value is None:
        return default.value
    normalized_value = str(value).strip().lower()
    if not normalized_value:
        return default.value
    return _LEGACY_ASYNC_TASK_STATUS_MAPPING.get(normalized_value, default.value)


def is_terminal_async_task_status(value: str | None) -> bool:
    """判断任务是否已经进入终态。"""

    normalized_value = normalize_async_task_status(value)
    return normalized_value in {
        AsyncTaskStatus.SUCCEEDED.value,
        AsyncTaskStatus.FAILED.value,
        AsyncTaskStatus.CANCELLED.value,
        AsyncTaskStatus.TIMED_OUT.value,
    }


__all__ = [
    "AsyncTaskStatus",
    "normalize_async_task_status",
    "is_terminal_async_task_status",
]
