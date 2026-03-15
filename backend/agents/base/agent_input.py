
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


@dataclass
class AgentInput:
    user_id: str
    conversation_id: str
    content: str
    message_id: Optional[str] = None
    conversation_history: Optional[List[Dict[str, str]]] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "content": self.content,
            "message_id": self.message_id,
            "conversation_history": self.conversation_history,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentInput":
        return cls(
            user_id=data.get("user_id", ""),
            conversation_id=data.get("conversation_id", ""),
            content=data.get("content", ""),
            message_id=data.get("message_id"),
            conversation_history=data.get("conversation_history"),
            metadata=data.get("metadata"),
        )

    def set_metadata(self, key: str, value: Any):
        if self.metadata is None:
            self.metadata = {}
        self.metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        if self.metadata is None:
            return default
        return self.metadata.get(key, default)

    def get_history_messages(self, max_messages: int = 100) -> List[Dict[str, str]]:
        if not self.conversation_history:
            return []

        # 只返回最近的max_messages条消息
        if len(self.conversation_history) > max_messages:
            return self.conversation_history[-max_messages:]
        return self.conversation_history

    def validate(self) -> tuple[bool, Optional[str]]:
        if not self.user_id:
            return False, "用户ID不能为空"
        if not self.conversation_id:
            return False, "会话ID不能为空"
        if not self.content:
            return False, "输入内容不能为空"
        return True, None

    def __repr__(self) -> str:
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"AgentInput(user_id='{self.user_id}', conversation_id='{self.conversation_id}', content='{preview}')"


@dataclass
class RouterAgentInput(AgentInput):
    available_agents: Optional[List[str]] = None

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["available_agents"] = self.available_agents
        return data


@dataclass
class RetrievalAgentInput(AgentInput):
    top_k: int = 5
    similarity_threshold: float = 0.7
    rerank: bool = True

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["top_k"] = self.top_k
        data["similarity_threshold"] = self.similarity_threshold
        data["rerank"] = self.rerank
        return data


@dataclass
class GenerationAgentInput(AgentInput):
    context: Optional[str] = None
    retrieval_results: Optional[List[Dict[str, Any]]] = None
    tool_results: Optional[List[Dict[str, Any]]] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["context"] = self.context
        data["retrieval_results"] = self.retrieval_results
        data["tool_results"] = self.tool_results
        data["temperature"] = self.temperature
        data["max_tokens"] = self.max_tokens
        return data


@dataclass
class ToolAgentInput(AgentInput):
    available_tools: Optional[List[str]] = None
    tool_timeout: int = 30

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["available_tools"] = self.available_tools
        data["tool_timeout"] = self.tool_timeout
        return data


@dataclass
class FileProcessorAgentInput(AgentInput):
    file_path: Optional[str] = None
    file_type: Optional[str] = None
    extract_images: bool = False
    extract_tables: bool = True

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["file_path"] = self.file_path
        data["file_type"] = self.file_type
        data["extract_images"] = self.extract_images
        data["extract_tables"] = self.extract_tables
        return data
