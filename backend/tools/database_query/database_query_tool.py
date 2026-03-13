"""
数据库查询工具
查询企业内部数据库（需要安全控制）
"""

from typing import Dict, Any
from backend.tools.base_tool import BaseTool, ToolDefinition, ToolParameter
from backend.database.database_manager import DatabaseManager


class DatabaseQueryTool(BaseTool):
    """
    数据库查询工具

    功能：
    - 查询企业内部数据库
    - 支持预定义的安全查询模板

    注意：
    - 为了安全，不支持任意SQL查询
    - 只支持预定义的查询模板
    - 需要配置数据库连接信息
    """

    def __init__(self):
        """初始化数据库查询工具"""
        super().__init__()
        # 初始化数据库管理器
        try:
            self.db_manager = DatabaseManager()
            self.logger.info("数据库管理器初始化成功")
        except Exception as e:
            self.logger.warning(f"数据库管理器初始化失败: {str(e)}")
            self.db_manager = None

        # 预定义的安全查询模板
        self.query_templates = {
            # 用户相关查询
            "user_count": "SELECT COUNT(*) as count FROM users",
            "user_info": "SELECT user_id, username, email, full_name, is_active, is_admin, created_at, last_login_at FROM users WHERE user_id = %s",
            "active_users": "SELECT user_id, username, email, full_name, last_login_at FROM users WHERE is_active = 1 ORDER BY last_login_at DESC LIMIT %s",

            # 会话相关查询
            "conversation_count": "SELECT COUNT(*) as count FROM conversations WHERE user_id = %s",
            "user_conversations": "SELECT conversation_id, title, message_count, created_at, updated_at FROM conversations WHERE user_id = %s AND is_active = 1 ORDER BY updated_at DESC LIMIT %s",
            "conversation_detail": "SELECT * FROM conversations WHERE conversation_id = %s",

            # 消息相关查询
            "recent_messages": "SELECT * FROM messages WHERE conversation_id = %s ORDER BY created_at DESC LIMIT %s",
            "message_count": "SELECT COUNT(*) as count FROM messages WHERE conversation_id = %s",
            "user_message_stats": "SELECT message_type, COUNT(*) as count FROM messages m JOIN conversations c ON m.conversation_id = c.conversation_id WHERE c.user_id = %s GROUP BY message_type",

            # 智能体执行相关查询
            "agent_executions": "SELECT execution_id, agent_name, agent_type, status, execution_time_ms, created_at FROM agent_executions WHERE conversation_id = %s ORDER BY created_at DESC LIMIT %s",
            "agent_stats": "SELECT agent_type, status, COUNT(*) as count, AVG(execution_time_ms) as avg_time FROM agent_executions WHERE conversation_id = %s GROUP BY agent_type, status",
            "failed_executions": "SELECT execution_id, agent_name, agent_type, error_message, created_at FROM agent_executions WHERE status = 'failed' AND conversation_id = %s ORDER BY created_at DESC LIMIT %s",

            # 工具调用相关查询
            "tool_calls": "SELECT call_id, tool_name, tool_type, status, execution_time_ms, created_at FROM tool_calls WHERE execution_id = %s ORDER BY created_at DESC LIMIT %s",
            "tool_stats": "SELECT tool_name, status, COUNT(*) as count, AVG(execution_time_ms) as avg_time FROM tool_calls tc JOIN agent_executions ae ON tc.execution_id = ae.execution_id WHERE ae.conversation_id = %s GROUP BY tool_name, status",

            # 文件相关查询
            "user_files": "SELECT file_id, original_filename, file_type, file_size, processing_status, created_at FROM files WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
            "file_detail": "SELECT * FROM files WHERE file_id = %s",
            "file_chunks": "SELECT chunk_id, chunk_index, page_number, token_count FROM file_chunks WHERE file_id = %s ORDER BY chunk_index ASC",

            # 检索结果相关查询
            "retrieval_results": "SELECT result_id, source_type, source_name, relevance_score, rank FROM retrieval_results WHERE execution_id = %s ORDER BY rank ASC LIMIT %s",

            # 内容生成相关查询
            "content_generations": "SELECT id, content_type, action, status, execution_time, created_at FROM content_generations WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
            "content_projects": "SELECT id, project_name, project_type, genre, status, word_count, chapter_count, last_edited_at FROM content_projects WHERE user_id = %s ORDER BY last_edited_at DESC LIMIT %s",
            "project_chapters": "SELECT id, chapter_number, chapter_title, word_count, status, updated_at FROM content_chapters WHERE project_id = %s ORDER BY chapter_number ASC",

            # 系统统计查询
            "system_stats": "SELECT (SELECT COUNT(*) FROM users) as total_users, (SELECT COUNT(*) FROM conversations) as total_conversations, (SELECT COUNT(*) FROM messages) as total_messages, (SELECT COUNT(*) FROM files) as total_files",
            "daily_activity": "SELECT DATE(created_at) as date, COUNT(*) as count FROM messages WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY) GROUP BY DATE(created_at) ORDER BY date DESC",
        }

    def _create_definition(self) -> ToolDefinition:
        """创建工具定义"""
        return ToolDefinition(
            name="database_query",
            description="查询企业内部数据库，支持预定义的安全查询模板，包括用户、会话、消息、智能体执行、工具调用、文件、内容生成等多种查询",
            category="data",
            parameters=[
                ToolParameter(
                    name="query_type",
                    type="string",
                    description=(
                        "查询类型，可选值：\n"
                        "用户相关：'user_count'（用户总数）、'user_info'（用户信息）、'active_users'（活跃用户列表）\n"
                        "会话相关：'conversation_count'（会话数量）、'user_conversations'（用户会话列表）、'conversation_detail'（会话详情）\n"
                        "消息相关：'recent_messages'（最近消息）、'message_count'（消息数量）、'user_message_stats'（用户消息统计）\n"
                        "智能体相关：'agent_executions'（智能体执行记录）、'agent_stats'（智能体统计）、'failed_executions'（失败执行记录）\n"
                        "工具相关：'tool_calls'（工具调用记录）、'tool_stats'（工具统计）\n"
                        "文件相关：'user_files'（用户文件列表）、'file_detail'（文件详情）、'file_chunks'（文件分块）\n"
                        "检索相关：'retrieval_results'（检索结果）\n"
                        "内容生成相关：'content_generations'（内容生成记录）、'content_projects'（内容项目）、'project_chapters'（项目章节）\n"
                        "系统统计：'system_stats'（系统统计）、'daily_activity'（每日活动统计）"
                    ),
                    required=True,
                    enum=[
                        "user_count", "user_info", "active_users",
                        "conversation_count", "user_conversations", "conversation_detail",
                        "recent_messages", "message_count", "user_message_stats",
                        "agent_executions", "agent_stats", "failed_executions",
                        "tool_calls", "tool_stats",
                        "user_files", "file_detail", "file_chunks",
                        "retrieval_results",
                        "content_generations", "content_projects", "project_chapters",
                        "system_stats", "daily_activity"
                    ]
                ),
                ToolParameter(
                    name="params",
                    type="object",
                    description="查询参数，根据查询类型提供不同的参数，如user_id、conversation_id、limit等",
                    required=False
                )
            ]
        )

    async def execute(self, query_type: str, params: dict = None, **kwargs) -> Dict[str, Any]:
        """
        执行数据库查询

        Args:
            query_type: 查询类型
            params: 查询参数

        Returns:
            查询结果
        """
        try:
            self.logger.info(f"开始数据库查询: 类型={query_type}, 参数={params}")

            # 检查查询类型是否支持
            if query_type not in self.query_templates:
                self.logger.warning(f"不支持的查询类型: {query_type}")
                return {
                    "success": False,
                    "data": None,
                    "error": f"不支持的查询类型：{query_type}"
                }

            # 检查数据库管理器是否可用
            if not self.db_manager:
                self.logger.error("数据库管理器未初始化")
                return {
                    "success": False,
                    "data": None,
                    "error": "数据库管理器未初始化"
                }

            # 获取查询模板
            query_template = self.query_templates[query_type]
            self.logger.debug(f"使用查询模板: {query_template}")

            # 执行查询
            result = await self._execute_query(query_type, query_template, params)

            self.logger.info(f"数据库查询完成: {query_type}")
            return {
                "success": True,
                "data": result,
                "error": None
            }

        except Exception as e:
            self.logger.error(f"数据库查询失败: {str(e)}", exc_info=True)
            return {
                "success": False,
                "data": None,
                "error": f"数据库查询失败：{str(e)}"
            }

    async def _execute_query(self, query_type: str, query_template: str, params: dict = None) -> dict:
        """
        执行具体的查询

        Args:
            query_type: 查询类型
            query_template: SQL查询模板
            params: 查询参数

        Returns:
            查询结果
        """
        try:
            # 准备查询参数
            query_params = self._prepare_query_params(query_type, params)

            # 执行查询
            if query_params:
                result = self.db_manager.execute_query(query_template, query_params)
            else:
                result = self.db_manager.execute_query(query_template)

            # 格式化结果
            formatted_result = self._format_query_result(query_type, result, params)

            self.logger.info(f"查询 {query_type} 成功，返回 {len(result) if result else 0} 条记录")
            return formatted_result

        except Exception as e:
            self.logger.error(f"执行查询 {query_type} 失败: {str(e)}", exc_info=True)
            return {
                "query_type": query_type,
                "error": str(e),
                "description": "查询执行失败"
            }

    def _prepare_query_params(self, query_type: str, params: dict = None) -> tuple:
        """
        准备查询参数

        Args:
            query_type: 查询类型
            params: 原始参数

        Returns:
            查询参数元组
        """
        if not params:
            params = {}

        # 根据查询类型准备参数
        param_mapping = {
            # 用户相关
            "user_info": ("user_id",),
            "active_users": ("limit",),

            # 会话相关
            "conversation_count": ("user_id",),
            "user_conversations": ("user_id", "limit"),
            "conversation_detail": ("conversation_id",),

            # 消息相关
            "recent_messages": ("conversation_id", "limit"),
            "message_count": ("conversation_id",),
            "user_message_stats": ("user_id",),

            # 智能体执行相关
            "agent_executions": ("conversation_id", "limit"),
            "agent_stats": ("conversation_id",),
            "failed_executions": ("conversation_id", "limit"),

            # 工具调用相关
            "tool_calls": ("execution_id", "limit"),
            "tool_stats": ("conversation_id",),

            # 文件相关
            "user_files": ("user_id", "limit"),
            "file_detail": ("file_id",),
            "file_chunks": ("file_id",),

            # 检索结果相关
            "retrieval_results": ("execution_id", "limit"),

            # 内容生成相关
            "content_generations": ("user_id", "limit"),
            "content_projects": ("user_id", "limit"),
            "project_chapters": ("project_id",),

            # 系统统计
            "daily_activity": ("days",),
        }

        if query_type not in param_mapping:
            return None

        # 提取参数值
        param_keys = param_mapping[query_type]
        param_values = []

        for key in param_keys:
            value = params.get(key)
            if value is None:
                # 设置默认值
                if key == "limit":
                    value = 10
                elif key == "days":
                    value = 7
                else:
                    raise ValueError(f"缺少必需参数：{key}")
            param_values.append(value)

        return tuple(param_values)

    def _format_query_result(self, query_type: str, result: list, params: dict = None) -> dict:
        """
        格式化查询结果

        Args:
            query_type: 查询类型
            result: 原始查询结果
            params: 查询参数

        Returns:
            格式化后的结果
        """
        if not params:
            params = {}

        # 统计类查询
        if query_type in ["user_count", "conversation_count", "message_count"]:
            count = result[0].get('count', 0) if result and len(result) > 0 else 0
            return {
                "query_type": query_type,
                "count": count,
                "description": f"查询结果：{count}"
            }

        # 列表类查询
        elif query_type in ["active_users", "user_conversations", "recent_messages", "agent_executions",
                            "failed_executions", "tool_calls", "user_files", "retrieval_results",
                            "content_generations", "content_projects", "project_chapters", "file_chunks"]:
            items = []
            if result:
                for row in result:
                    # 转换时间戳为字符串
                    item = {}
                    for key, value in row.items():
                        if hasattr(value, 'isoformat'):  # datetime对象
                            item[key] = value.isoformat()
                        else:
                            item[key] = value
                    items.append(item)

            return {
                "query_type": query_type,
                "items": items,
                "count": len(items),
                "description": f"查询到 {len(items)} 条记录"
            }

        # 详情类查询
        elif query_type in ["user_info", "conversation_detail", "file_detail"]:
            if result and len(result) > 0:
                detail = {}
                for key, value in result[0].items():
                    if hasattr(value, 'isoformat'):
                        detail[key] = value.isoformat()
                    else:
                        detail[key] = value
                return {
                    "query_type": query_type,
                    "detail": detail,
                    "description": "查询成功"
                }
            else:
                return {
                    "query_type": query_type,
                    "detail": None,
                    "description": "未找到记录"
                }

        # 统计类查询（分组）
        elif query_type in ["user_message_stats", "agent_stats", "tool_stats"]:
            stats = []
            if result:
                for row in result:
                    stats.append(dict(row))
            return {
                "query_type": query_type,
                "stats": stats,
                "description": f"统计结果：{len(stats)} 个分组"
            }

        # 系统统计
        elif query_type == "system_stats":
            if result and len(result) > 0:
                return {
                    "query_type": query_type,
                    "stats": dict(result[0]),
                    "description": "系统统计数据"
                }
            else:
                return {
                    "query_type": query_type,
                    "stats": {},
                    "description": "无统计数据"
                }

        # 每日活动统计
        elif query_type == "daily_activity":
            activity = []
            if result:
                for row in result:
                    activity.append({
                        "date": str(row.get('date')),
                        "count": row.get('count', 0)
                    })
            return {
                "query_type": query_type,
                "activity": activity,
                "description": f"最近 {params.get('days', 7)} 天的活动统计"
            }

        # 默认格式
        else:
            return {
                "query_type": query_type,
                "data": result,
                "description": "查询完成"
            }
