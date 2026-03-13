"""
数据模型模块

包含所有数据模型定义：
- User: 用户模型
- Conversation: 会话模型
- ConversationState: 会话状态模型
- Message: 消息模型
- AgentExecution: 智能体执行记录模型
- ToolCall: 工具调用模型
- RetrievalResult: 检索结果模型
- File: 文件模型
- FileChunk: 文件分块模型
"""

# User models
from backend.models.user import (
    User,
    UserCreate,
    UserUpdate,
    UserLogin
)

# Conversation models
from backend.models.conversation import (
    Conversation,
    ConversationCreate,
    ConversationUpdate,
    ConversationSummary
)

# Conversation state models
from backend.models.conversation_state import (
    ConversationState,
    ConversationStateCreate,
    ConversationStateUpdate,
    ConversationStateSummary
)

# Message models
from backend.models.message import (
    Message,
    MessageCreate,
    MessageUpdate,
    MessageType
)

# Agent execution models
from backend.models.agent_execution import (
    AgentExecution,
    AgentExecutionCreate,
    AgentExecutionUpdate,
    AgentType,
    ExecutionStatus
)

# Tool call models
from backend.models.tool_call import (
    ToolCall,
    ToolCallCreate,
    ToolCallUpdate,
    ToolCallSummary,
    ToolCallStatus
)

# Retrieval result models
from backend.models.retrieval_result import (
    RetrievalResult,
    RetrievalResultCreate,
    RetrievalResultSummary
)

# File models
from backend.models.file import (
    File,
    FileCreate,
    FileUpdate,
    FileChunk,
    FileType,
    ProcessingStatus
)

__all__ = [
    # User
    "User",
    "UserCreate",
    "UserUpdate",
    "UserLogin",

    # Conversation
    "Conversation",
    "ConversationCreate",
    "ConversationUpdate",
    "ConversationSummary",

    # Conversation State
    "ConversationState",
    "ConversationStateCreate",
    "ConversationStateUpdate",
    "ConversationStateSummary",

    # Message
    "Message",
    "MessageCreate",
    "MessageUpdate",
    "MessageType",

    # Agent Execution
    "AgentExecution",
    "AgentExecutionCreate",
    "AgentExecutionUpdate",
    "AgentType",
    "ExecutionStatus",

    # Tool Call
    "ToolCall",
    "ToolCallCreate",
    "ToolCallUpdate",
    "ToolCallSummary",
    "ToolCallStatus",

    # Retrieval Result
    "RetrievalResult",
    "RetrievalResultCreate",
    "RetrievalResultSummary",

    # File
    "File",
    "FileCreate",
    "FileUpdate",
    "FileChunk",
    "FileType",
    "ProcessingStatus",
]
