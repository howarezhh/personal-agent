"""
自定义异常类
定义项目中使用的所有自定义异常
"""


class PersonalAgentException(Exception):
    """
    项目基础异常类
    所有自定义异常都应该继承此类
    """
    def __init__(self, message: str, code: str = None, details: dict = None):
        self.message = message
        self.code = code or "UNKNOWN_ERROR"
        self.details = details or {}
        super().__init__(self.message)


# 配置相关异常
class ConfigurationError(PersonalAgentException):
    """配置错误"""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message, "CONFIG_ERROR", details)


# 数据库相关异常
class DatabaseError(PersonalAgentException):
    """数据库错误"""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message, "DATABASE_ERROR", details)


class RecordNotFoundError(DatabaseError):
    """记录不存在"""
    def __init__(self, model: str, identifier: str):
        super().__init__(
            f"{model} 未找到: {identifier}",
            {"model": model, "identifier": identifier}
        )


# 认证相关异常
class AuthenticationError(PersonalAgentException):
    """认证错误"""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message, "AUTH_ERROR", details)


# 智能体相关异常
class AgentError(PersonalAgentException):
    """智能体错误"""
    def __init__(self, message: str, agent_name: str = None, details: dict = None):
        details = details or {}
        if agent_name:
            details["agent_name"] = agent_name
        super().__init__(message, "AGENT_ERROR", details)


# 文件处理相关异常
class FileProcessingError(PersonalAgentException):
    """文件处理错误"""
    def __init__(self, message: str, file_path: str = None, details: dict = None):
        details = details or {}
        if file_path:
            details["file_path"] = file_path
        super().__init__(message, "FILE_PROCESSING_ERROR", details)


# 工具调用相关异常
class ToolError(PersonalAgentException):
    """工具调用错误"""
    def __init__(self, message: str, tool_name: str = None, details: dict = None):
        details = details or {}
        if tool_name:
            details["tool_name"] = tool_name
        super().__init__(message, "TOOL_ERROR", details)


# 验证相关异常
class ValidationError(PersonalAgentException):
    """数据验证错误"""
    def __init__(self, message: str, field: str = None, details: dict = None):
        details = details or {}
        if field:
            details["field"] = field
        super().__init__(message, "VALIDATION_ERROR", details)
