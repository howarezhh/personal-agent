from __future__ import annotations

from typing import Any, Dict, Optional

from backend.contracts.errors import ErrorCode
from backend.models.agent_execution import AgentExecutionCreate, AgentExecutionUpdate
from backend.utils.error_utils import build_error_metadata, sanitize_error_message


class AgentExecutionApplicationService:
    """Application service for agent execution records."""

    def __init__(self, *, repository):
        self.repository = repository

    def create_execution(self, execution_create: AgentExecutionCreate):
        return self.repository.create_execution(execution_create)

    def update_execution(self, execution_id: str, execution_update: AgentExecutionUpdate):
        normalized_update = AgentExecutionUpdate(
            output_data=self._normalize_output_data(execution_update.output_data),
            status=execution_update.status,
            error_message=self._normalize_error_message(execution_update.error_message),
            execution_time_ms=execution_update.execution_time_ms,
            completed_at=execution_update.completed_at,
            metadata=self._normalize_metadata(
                status=execution_update.status,
                error_message=execution_update.error_message,
                output_data=execution_update.output_data,
                metadata=execution_update.metadata,
            ),
        )
        return self.repository.update_execution(execution_id, normalized_update)

    def create_execution_with_result(
        self,
        agent_name: str,
        agent_type: str,
        input_data: dict,
        output_data: dict,
        status: str,
        execution_time_ms: int,
        conversation_id: Optional[str] = None,
        message_id: Optional[str] = None,
        error_message: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        normalized_output = self._normalize_output_data(output_data)
        normalized_error = self._normalize_error_message(error_message)
        normalized_metadata = self._normalize_metadata(
            status=status,
            error_message=error_message,
            output_data=output_data,
            metadata=metadata,
        )
        return self.repository.create_execution_with_result(
            agent_name=agent_name,
            agent_type=agent_type,
            input_data=input_data,
            output_data=normalized_output,
            status=status,
            execution_time_ms=execution_time_ms,
            conversation_id=conversation_id,
            message_id=message_id,
            error_message=normalized_error,
            metadata=normalized_metadata,
        )

    @staticmethod
    def _normalize_error_message(error_message: Any) -> Optional[str]:
        if error_message is None:
            return None
        return sanitize_error_message(error_message, fallback="agent execution failed")

    @staticmethod
    def _normalize_output_data(output_data: Any) -> Any:
        if not isinstance(output_data, dict):
            return output_data
        normalized_output = dict(output_data)
        if "error" in normalized_output:
            normalized_output["error"] = sanitize_error_message(
                normalized_output.get("error"),
                fallback="agent execution failed",
            )
        return normalized_output

    @staticmethod
    def _normalize_metadata(
        *,
        status: Optional[str],
        error_message: Any,
        output_data: Any,
        metadata: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        normalized_metadata = dict(metadata or {})
        output_error_code = output_data.get("error_code") if isinstance(output_data, dict) else None
        output_error_type = output_data.get("error_type") if isinstance(output_data, dict) else None
        if status == "failed" or error_message is not None or output_error_code:
            return build_error_metadata(
                error_code=output_error_code or normalized_metadata.get("error_code") or ErrorCode.SYSTEM_INTERNAL_ERROR.value,
                error_type=output_error_type or normalized_metadata.get("error_type") or "execution_error",
                metadata=normalized_metadata,
            )
        return normalized_metadata or None
