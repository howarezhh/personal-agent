from __future__ import annotations

import json
from typing import Any

from backend.contracts.errors import ErrorCode
from backend.contracts.sse import build_sse_event
from backend.contracts.task_runtime import TaskRuntimeControllerEvent


class TaskRuntimeEventTranslator:
    """将任务运行时内部事件翻译为统一 SSE 事件。"""

    def translate(self, event: TaskRuntimeControllerEvent) -> dict[str, Any]:
        """把内部事件转换为统一 SSE 载荷。"""
        event_type = self._resolve_event_type(event)
        metadata = self._build_metadata(event)
        content = self._resolve_content(event)
        citations = self._resolve_citations(event)
        error_code = self._resolve_error_code(event)
        return build_sse_event(
            event_type,
            content,
            message=event.message or self._default_message(event),
            metadata=metadata,
            request_id=event.request_id,
            conversation_id=event.conversation_id,
            message_id=event.message_id,
            execution_id=event.execution_id,
            error_code=error_code,
            citations=citations or None,
        )

    def format_sse(self, event: TaskRuntimeControllerEvent) -> str:
        """输出标准 SSE 文本块。"""
        payload = self.translate(event)
        return f"event: {payload['type']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def format_error(
        self,
        *,
        error_message: str,
        request_id: str | None,
        conversation_id: str | None,
        message_id: str | None,
        execution_id: str | None,
        error_code: str | None = None,
    ) -> str:
        """生成统一错误 SSE。"""
        metadata = {
            "stage": "termination",
            "request_id": request_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "execution_id": execution_id,
            "plan_id": None,
            "step_id": None,
            "error_code": error_code or ErrorCode.WORKFLOW_EXECUTION_ERROR.value,
        }
        payload = build_sse_event(
            "error",
            None,
            message=error_message,
            metadata=metadata,
            request_id=request_id,
            conversation_id=conversation_id,
            message_id=message_id,
            execution_id=execution_id,
            error_code=error_code or ErrorCode.WORKFLOW_EXECUTION_ERROR.value,
        )
        return f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def _resolve_event_type(self, event: TaskRuntimeControllerEvent) -> str:
        """根据阶段和载荷决定 SSE 事件类型。"""
        if event.stage == "termination":
            termination = event.payload.get("termination") or {}
            return "error" if termination.get("status") == "failed" else "done"
        if event.stage in {"planning", "replan"}:
            return "result"
        if event.stage == "step_started":
            step = event.payload.get("step") or {}
            return "tool_call" if step.get("step_type") == "tool_call" else "thinking"
        if event.stage == "step_observation":
            step = event.payload.get("step") or {}
            if step.get("step_type") == "tool_call":
                return "tool_call"
            if step.get("step_type") == "synthesize_answer":
                return "content"
            return "result"
        return "thinking"

    def _build_metadata(self, event: TaskRuntimeControllerEvent) -> dict[str, Any]:
        """统一补齐前端消费所需的链路与阶段信息。"""
        metadata: dict[str, Any] = {
            "stage": event.stage,
            "request_id": event.request_id,
            "conversation_id": event.conversation_id,
            "message_id": event.message_id,
            "execution_id": event.execution_id,
            "plan_id": event.plan_id,
            "step_id": event.step_id,
        }
        if event.stage == "step_evaluation":
            evaluation = event.payload.get("step_evaluation") or {}
            metadata["next_action"] = evaluation.get("next_action")
            metadata["quality_score"] = evaluation.get("quality_score")
        if event.stage == "termination":
            termination = event.payload.get("termination") or {}
            metadata["status"] = termination.get("status")
        resolved_error_code = self._resolve_error_code(event)
        if resolved_error_code:
            metadata["error_code"] = resolved_error_code
        return metadata

    def _resolve_content(self, event: TaskRuntimeControllerEvent) -> Any:
        """根据事件类型选择最适合的 content。"""
        if event.stage == "step_observation":
            step = event.payload.get("step") or {}
            observation = event.payload.get("observation") or {}
            if step.get("step_type") == "synthesize_answer":
                return observation.get("output_data", {}).get("final_output") or observation.get("summary")
            return event.payload
        if event.stage == "termination":
            return event.payload.get("final_output") or event.payload.get("termination") or {}
        if event.stage == "goal_parsing":
            return event.payload.get("goal") or event.payload
        if event.stage in {"planning", "replan"}:
            return event.payload.get("plan") or event.payload
        return event.payload

    @staticmethod
    def _resolve_citations(event: TaskRuntimeControllerEvent) -> list[dict[str, Any]]:
        """从控制器事件中提取统一引用列表。"""
        raw_citations = event.payload.get("citations")
        if not isinstance(raw_citations, list) and event.stage == "step_observation":
            observation = event.payload.get("observation") or {}
            if isinstance(observation, dict):
                output_data = observation.get("output_data") or {}
                if isinstance(output_data, dict):
                    raw_citations = output_data.get("citations")

        if not isinstance(raw_citations, list):
            return []
        return [dict(item) for item in raw_citations if isinstance(item, dict)]

    @staticmethod
    def _resolve_error_code(event: TaskRuntimeControllerEvent) -> str | None:
        """统一推导公开 SSE 错误码。"""
        payload_error_code = event.payload.get("error_code")
        if isinstance(payload_error_code, str) and payload_error_code:
            return payload_error_code

        if event.stage != "termination":
            return None

        termination = event.payload.get("termination") or {}
        status = termination.get("status")
        if status == "failed":
            return ErrorCode.WORKFLOW_EXECUTION_ERROR.value
        if status == "blocked":
            return ErrorCode.WORKFLOW_INVALID_INPUT.value
        return None

    @staticmethod
    def _default_message(event: TaskRuntimeControllerEvent) -> str:
        """为缺失 message 的事件补默认说明。"""
        defaults = {
            "goal_parsing": "已完成目标解析。",
            "planning": "已完成计划生成。",
            "step_started": "步骤开始执行。",
            "step_observation": "步骤已产出执行结果。",
            "step_evaluation": "步骤已完成质量评估。",
            "goal_evaluation": "已完成整体目标评估。",
            "replan": "已完成重规划决策。",
            "termination": "任务执行结束。",
        }
        return defaults.get(event.stage, "任务运行时事件。")
