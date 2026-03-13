"""
日志管理模块
提供统一的日志记录功能
"""

import os
import sys
import logging
import json
from typing import Optional, Dict, Any
from pathlib import Path
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from datetime import datetime, timezone


_STANDARD_LOG_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__.keys())


def _ensure_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue

        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


class StructuredFormatter(logging.Formatter):
    """
    结构化日志格式化器
    将日志输出为JSON格式，便于日志收集和分析
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        格式化日志记录为JSON字符串

        Args:
            record: 日志记录对象

        Returns:
            JSON格式的日志字符串
        """
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 添加异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # 添加额外的字段，兼容 logging extra=... 与自定义 extra_fields 两种写法
        extra_fields: Dict[str, Any] = {}
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            extra_fields.update(record.extra_fields)

        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_RECORD_FIELDS or key == "extra_fields" or key.startswith("_"):
                continue
            extra_fields.setdefault(key, value)

        if extra_fields:
            log_data.update(extra_fields)

        return json.dumps(log_data, ensure_ascii=False)


class LoggerManager:
    """
    日志管理器

    功能：
    1. 配置日志级别
    2. 日志输出到文件和控制台
    3. 支持结构化日志（JSON格式）
    4. 日志轮转（按大小或时间）
    5. 不同模块使用不同的日志记录器
    """

    def __init__(
        self,
        log_dir: str = None,
        log_level: str = "INFO",
        enable_console: bool = True,
        enable_file: bool = True,
        enable_structured: bool = False,
        rotation_type: str = "size",  # size or time
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
        when: str = "midnight",  # 时间轮转：midnight, H, D, W0-W6
    ):
        """
        初始化日志管理器

        Args:
            log_dir: 日志文件目录，默认为项目根目录下的logs文件夹
            log_level: 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
            enable_console: 是否输出到控制台
            enable_file: 是否输出到文件
            enable_structured: 是否使用结构化日志（JSON格式）
            rotation_type: 日志轮转类型（size按大小，time按时间）
            max_bytes: 单个日志文件最大字节数（仅size轮转）
            backup_count: 保留的日志文件数量
            when: 时间轮转周期（仅time轮转）
        """
        _ensure_utf8_stdio()

        if log_dir is None:
            # 动态查找项目根目录
            from backend.utils.path_utils import find_project_root
            project_root = find_project_root(Path(__file__).parent)
            log_dir = project_root / "logs"

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.log_level = getattr(logging, log_level.upper(), logging.INFO)
        self.enable_console = enable_console
        self.enable_file = enable_file
        self.enable_structured = enable_structured
        self.rotation_type = rotation_type
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.when = when

        # 存储已创建的logger
        self._loggers: Dict[str, logging.Logger] = {}

        # 配置根日志记录器
        self._configure_root_logger()

    def _configure_root_logger(self):
        """配置根日志记录器"""
        root_logger = logging.getLogger()
        root_logger.setLevel(self.log_level)

        # 清除已有的处理器
        root_logger.handlers.clear()

    def _create_console_handler(self) -> logging.Handler:
        """
        创建控制台处理器

        Returns:
            控制台处理器
        """
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self.log_level)

        if self.enable_structured:
            formatter = StructuredFormatter()
        else:
            formatter = logging.Formatter(
                fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )

        console_handler.setFormatter(formatter)
        return console_handler

    def _create_file_handler(self, log_file: str) -> logging.Handler:
        """
        创建文件处理器

        Args:
            log_file: 日志文件名

        Returns:
            文件处理器
        """
        log_path = self.log_dir / log_file

        if self.rotation_type == "size":
            # 按大小轮转
            file_handler = RotatingFileHandler(
                filename=log_path,
                maxBytes=self.max_bytes,
                backupCount=self.backup_count,
                encoding="utf-8"
            )
        else:
            # 按时间轮转
            file_handler = TimedRotatingFileHandler(
                filename=log_path,
                when=self.when,
                backupCount=self.backup_count,
                encoding="utf-8"
            )

        file_handler.setLevel(self.log_level)

        if self.enable_structured:
            formatter = StructuredFormatter()
        else:
            formatter = logging.Formatter(
                fmt="%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(funcName)s:%(lineno)d - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )

        file_handler.setFormatter(formatter)
        return file_handler

    def get_logger(self, name: str, log_file: str = None) -> logging.Logger:
        """
        获取日志记录器

        Args:
            name: 日志记录器名称（通常使用模块名）
            log_file: 日志文件名，如果为None则使用默认文件名

        Returns:
            日志记录器实例
        """
        # 如果已存在，直接返回
        if name in self._loggers:
            return self._loggers[name]

        # 创建新的logger
        logger = logging.getLogger(name)
        logger.setLevel(self.log_level)
        logger.propagate = False  # 不传播到父logger
        logger.handlers.clear()

        # 添加控制台处理器
        if self.enable_console:
            console_handler = self._create_console_handler()
            logger.addHandler(console_handler)

        # 添加文件处理器
        if self.enable_file:
            if log_file is None:
                # 使用默认文件名
                log_file = f"{name.replace('.', '_')}.log"
            file_handler = self._create_file_handler(log_file)
            logger.addHandler(file_handler)

        # 缓存logger
        self._loggers[name] = logger

        return logger

    def set_level(self, level: str):
        """
        设置全局日志级别

        Args:
            level: 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
        """
        self.log_level = getattr(logging, level.upper(), logging.INFO)

        # 更新所有已创建的logger
        for logger in self._loggers.values():
            logger.setLevel(self.log_level)
            for handler in logger.handlers:
                handler.setLevel(self.log_level)

    def log_with_context(
        self,
        logger: logging.Logger,
        level: str,
        message: str,
        **context
    ):
        """
        记录带上下文信息的日志

        Args:
            logger: 日志记录器
            level: 日志级别
            message: 日志消息
            **context: 上下文信息（键值对）
        """
        log_level = getattr(logging, level.upper(), logging.INFO)

        # 创建日志记录
        record = logger.makeRecord(
            logger.name,
            log_level,
            "(unknown file)",
            0,
            message,
            (),
            None
        )

        # 添加额外字段
        record.extra_fields = context

        # 处理日志
        logger.handle(record)

    def __repr__(self) -> str:
        return f"LoggerManager(log_dir='{self.log_dir}', level={logging.getLevelName(self.log_level)})"


# 全局日志管理器实例
_logger_manager: Optional[LoggerManager] = None


def get_logger_manager(
    log_dir: str = None,
    log_level: str = None,
    **kwargs
) -> LoggerManager:
    """
    获取全局日志管理器实例（单例模式）

    Args:
        log_dir: 日志文件目录
        log_level: 日志级别
        **kwargs: 其他配置参数

    Returns:
        LoggerManager实例
    """
    global _logger_manager

    if _logger_manager is None:
        config_options: Dict[str, Any] = {}
        if log_dir is None:
            try:
                from backend.core.config_manager import get_config_manager

                config_manager = get_config_manager()
                logging_config = config_manager.get_business_config("logging", {}) or {}
                file_config = logging_config.get("file", {}) or {}

                log_dir = file_config.get("directory")

                outputs = logging_config.get("output", []) or []
                if not isinstance(outputs, (list, tuple, set)):
                    outputs = [outputs]

                config_options = {
                    "enable_console": "console" in outputs if outputs else True,
                    "enable_file": "file" in outputs if outputs else True,
                    "enable_structured": str(logging_config.get("format", "")).lower() == "json",
                    "rotation_type": "time" if str(file_config.get("rotation", "size")).lower() == "time" else "size",
                    "max_bytes": int(file_config.get("max_bytes", 10 * 1024 * 1024)),
                    "backup_count": int(file_config.get("backup_count", 5)),
                    "when": file_config.get("when", "midnight"),
                }

                if log_level is None:
                    log_level = logging_config.get("level")
            except Exception:
                log_dir = None
                config_options = {}

        # 从环境变量读取配置
        if log_level is None:
            log_level = os.environ.get("LOG_LEVEL", "INFO")

        manager_options = {**config_options, **kwargs}
        _logger_manager = LoggerManager(
            log_dir=log_dir,
            log_level=log_level,
            **manager_options
        )

    return _logger_manager


def get_logger(name: str, log_file: str = None) -> logging.Logger:
    """
    获取日志记录器（便捷函数）

    Args:
        name: 日志记录器名称
        log_file: 日志文件名

    Returns:
        日志记录器实例
    """
    manager = get_logger_manager()
    return manager.get_logger(name, log_file)


def log_agent_execution(
    logger: logging.Logger,
    agent_name: str,
    agent_type: str,
    execution_id: str,
    status: str,
    execution_time_ms: float,
    **metadata
):
    """
    记录智能体执行日志（结构化）

    Args:
        logger: 日志记录器
        agent_name: 智能体名称
        agent_type: 智能体类型
        execution_id: 执行ID
        status: 执行状态
        execution_time_ms: 执行时间（毫秒）
        **metadata: 其他元数据
    """
    context = {
        "event_type": "agent_execution",
        "agent_name": agent_name,
        "agent_type": agent_type,
        "execution_id": execution_id,
        "status": status,
        "execution_time_ms": execution_time_ms,
        **metadata
    }

    message = f"智能体 {agent_name} 执行完成，状态 {status}，耗时 {execution_time_ms}毫秒"

    manager = get_logger_manager()
    manager.log_with_context(logger, "INFO", message, **context)


def log_api_request(
    logger: logging.Logger,
    method: str,
    path: str,
    status_code: int,
    response_time_ms: float,
    user_id: str = None,
    **metadata
):
    """
    记录API请求日志（结构化）

    Args:
        logger: 日志记录器
        method: HTTP方法
        path: 请求路径
        status_code: 响应状态码
        response_time_ms: 响应时间（毫秒）
        user_id: 用户ID
        **metadata: 其他元数据
    """
    context = {
        "event_type": "api_request",
        "method": method,
        "path": path,
        "status_code": status_code,
        "response_time_ms": response_time_ms,
        **metadata
    }

    if user_id:
        context["user_id"] = user_id

    message = f"{method} {path} - {status_code} - {response_time_ms}毫秒"

    manager = get_logger_manager()
    manager.log_with_context(logger, "INFO", message, **context)


def log_database_operation(
    logger: logging.Logger,
    operation: str,
    table: str,
    success: bool,
    execution_time_ms: float,
    **metadata
):
    """
    记录数据库操作日志（结构化）

    Args:
        logger: 日志记录器
        operation: 操作类型（SELECT/INSERT/UPDATE/DELETE）
        table: 表名
        success: 是否成功
        execution_time_ms: 执行时间（毫秒）
        **metadata: 其他元数据
    """
    context = {
        "event_type": "database_operation",
        "operation": operation,
        "table": table,
        "success": success,
        "execution_time_ms": execution_time_ms,
        **metadata
    }

    status = "成功" if success else "失败"
    message = f"数据库 {operation} 操作于 {table} - {status} - {execution_time_ms}毫秒"

    level = "INFO" if success else "ERROR"
    manager = get_logger_manager()
    manager.log_with_context(logger, level, message, **context)
