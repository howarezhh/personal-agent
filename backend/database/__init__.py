"""
数据库模块
提供数据库连接、管理和数据访问功能
"""

from backend.database.database_manager import DatabaseManager, get_database_manager
from backend.database.connection_pool import ConnectionPool, get_connection_pool, close_connection_pool

# 导出所有 Repository
from backend.database.repositories.user_repository import (
    BaseRepository,
    UserRepository,
    get_user_repository
)
from backend.database.repositories.conversation_repository import (
    ConversationRepository,
    get_conversation_repository
)
from backend.database.repositories.message_repository import (
    MessageRepository,
    get_message_repository
)
from backend.database.repositories.agent_execution_repository import (
    AgentExecutionRepository,
    get_agent_execution_repository
)
from backend.database.repositories.file_repository import (
    FileRepository,
    get_file_repository
)

__all__ = [
    # 数据库管理
    'DatabaseManager',
    'get_database_manager',

    # 连接池管理
    'ConnectionPool',
    'get_connection_pool',
    'close_connection_pool',

    # 基础仓储
    'BaseRepository',

    # 用户仓储
    'UserRepository',
    'get_user_repository',

    # 会话仓储
    'ConversationRepository',
    'get_conversation_repository',

    # 消息仓储
    'MessageRepository',
    'get_message_repository',

    # 智能体执行记录仓储
    'AgentExecutionRepository',
    'get_agent_execution_repository',

    # 文件仓储
    'FileRepository',
    'get_file_repository',
]
