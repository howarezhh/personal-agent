from __future__ import annotations

from typing import Any, AsyncGenerator, Optional

from backend.application.services.chat_service_support import ChatServiceSupport, PreparedChatTurn
from backend.application.services.chat_turn_preparation_application_service import ChatTurnPreparationApplicationService
from backend.application.services.workflow_application_service import WorkflowApplicationService
from backend.utils.citation_utils import replace_citation_placeholders


class ChatExecutionApplicationService:
    """聊天执行服务，负责消费工作流输出并落助手消息。"""

    def __init__(
        self,
        *,
        workflow_service: WorkflowApplicationService | None = None,
        support_service: ChatServiceSupport,
        preparation_service: ChatTurnPreparationApplicationService,
    ):
        self.workflow_service = workflow_service or WorkflowApplicationService()
        self.support_service = support_service
        self.preparation_service = preparation_service

    @staticmethod
    def extract_result_answer(payload: Any) -> str:
        """从 result 事件中提取最终答案文本。"""
        if not isinstance(payload, dict):
            return ""

        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        if metadata.get("result_scope") == "step":
            return ""

        value = payload.get("final_content")
        if isinstance(value, str) and value.strip():
            return value
        return ""

    @staticmethod
    def extract_execution_id(payload: Any) -> Optional[str]:
        """从 chunk 或 payload 中统一提取执行 ID。"""
        if hasattr(payload, "metadata") and isinstance(getattr(payload, "metadata", None), dict):
            metadata = getattr(payload, "metadata")
            if metadata.get("execution_id"):
                return str(metadata["execution_id"])

        if hasattr(payload, "content") and isinstance(getattr(payload, "content", None), dict):
            content = getattr(payload, "content")
            if content.get("execution_id"):
                return str(content["execution_id"])

        if isinstance(payload, dict) and payload.get("execution_id"):
            return str(payload["execution_id"])

        return None

    @staticmethod
    def build_event_payload(chunk: Any) -> Any:
        """将工作流原始 chunk 统一映射为 API 层可消费的事件负载。"""
        if chunk.chunk_type == "tool_call":
            payload = dict(chunk.metadata) if chunk.metadata else {}
            if chunk.content and "message" not in payload:
                payload["message"] = chunk.content
            return payload or chunk.content

        if chunk.chunk_type == "result":
            if isinstance(chunk.content, dict):
                payload = dict(chunk.content)
            else:
                payload = {"content": chunk.content}
            if chunk.metadata:
                payload.setdefault("metadata", dict(chunk.metadata))
            return payload

        if chunk.chunk_type == "metadata":
            if chunk.metadata:
                return dict(chunk.metadata)
            if isinstance(chunk.content, dict):
                return dict(chunk.content)
            return {"value": chunk.content}

        return chunk.content

    def _build_assistant_metadata(self, *, turn: PreparedChatTurn, execution_id: Optional[str]) -> dict[str, Any]:
        """构造助手消息落库所需的统一元数据。"""
        return {
            "request_id": turn.request_id,
            "conversation_id": turn.conversation_id,
            "execution_id": execution_id,
            "knowledge_base_id": turn.knowledge_base_id,
        }

    def _save_final_answer(
        self,
        *,
        turn: PreparedChatTurn,
        answer: str,
        citations: list[Any],
        execution_id: Optional[str],
    ) -> Optional[str]:
        """统一保存最终助手消息，并返回助手消息 ID。"""
        if not answer:
            return None

        assistant_message = self.support_service.save_assistant_message(
            conversation_id=turn.conversation_id,
            content=answer,
            citations=citations,
            parent_message_id=turn.user_message_id,
            metadata=self._build_assistant_metadata(turn=turn, execution_id=execution_id),
        )
        return assistant_message.message_id if assistant_message else None

    async def execute_stream_turn(self, *, turn: PreparedChatTurn) -> AsyncGenerator[dict[str, Any], None]:
        """执行流式聊天轮次，并把结果转换为统一事件结构。"""
        agent_input = self.preparation_service.build_agent_input_for_turn(turn)
        full_answer = ""
        workflow_final_content = ""
        citations: list[Any] = []
        execution_id: Optional[str] = None

        async for chunk in self.workflow_service.execute_stream(agent_input):
            event_type = chunk.chunk_type
            payload = self.build_event_payload(chunk)
            execution_id = self.extract_execution_id(chunk) or self.extract_execution_id(payload) or execution_id

            if event_type == "content":
                full_answer += chunk.content
            elif event_type == "result":
                if isinstance(payload, dict) and "citations" in payload:
                    citations = payload.get("citations", []) or citations
                if not full_answer and not workflow_final_content:
                    workflow_final_content = self.extract_result_answer(payload)
            elif event_type == "error":
                yield {
                    "event_type": "error",
                    "data": chunk.content,
                    "execution_id": execution_id,
                    "metadata": chunk.metadata,
                }
                return

            yield {
                "event_type": event_type,
                "data": payload if event_type in {"tool_call", "result", "metadata"} else chunk.content,
                "execution_id": execution_id,
                "metadata": chunk.metadata,
            }

        normalized_answer = replace_citation_placeholders(full_answer or workflow_final_content, citations)
        assistant_message_id = self._save_final_answer(
            turn=turn,
            answer=normalized_answer,
            citations=citations,
            execution_id=execution_id,
        )
        yield {
            "event_type": "done",
            "data": {
                "conversation_id": turn.conversation_id,
                "assistant_message_id": assistant_message_id,
                "citations": citations,
                "final_content": normalized_answer,
                "execution_id": execution_id,
            },
            "execution_id": execution_id,
            "metadata": None,
        }

    async def execute_non_stream_turn(self, *, turn: PreparedChatTurn) -> dict[str, Any]:
        """执行非流式聊天轮次，并返回聚合后的最终结果。"""
        agent_input = self.preparation_service.build_agent_input_for_turn(turn)
        full_answer = ""
        workflow_final_content = ""
        citations: list[Any] = []
        execution_id: Optional[str] = None

        async for chunk in self.workflow_service.execute_stream(agent_input):
            if chunk.chunk_type == "content":
                full_answer += chunk.content
            elif chunk.chunk_type == "result":
                payload = self.build_event_payload(chunk)
                if isinstance(payload, dict) and "citations" in payload:
                    citations = payload.get("citations", []) or citations
                if not full_answer and not workflow_final_content:
                    workflow_final_content = self.extract_result_answer(payload)
                execution_id = self.extract_execution_id(chunk) or self.extract_execution_id(payload) or execution_id
            elif chunk.chunk_type == "error":
                raise RuntimeError(str(chunk.content))
            execution_id = self.extract_execution_id(chunk) or execution_id

        normalized_answer = replace_citation_placeholders(full_answer or workflow_final_content, citations)
        assistant_message_id = self._save_final_answer(
            turn=turn,
            answer=normalized_answer,
            citations=citations,
            execution_id=execution_id,
        )
        return {
            "answer": normalized_answer,
            "execution_id": execution_id,
            "assistant_message_id": assistant_message_id,
            "citations": citations,
        }

