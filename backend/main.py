"""
FastAPI主应用
企业级多Agent知识库助手系统的主入口
"""

# 必须在所有其他导入之前加载环境变量
from backend.core.env_loader import load_environment
load_environment()

import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import uvicorn

# 添加项目根目录到Python路径

from backend.api import auth, chat, conversations, knowledge, tools, content_generation
from backend.api.models import ErrorResponse, ErrorDetail, MessageResponse
from backend.api.middleware import RequestIDMiddleware
from backend.contracts.errors import ErrorCode, infer_error_code
from backend.core.config_manager import get_config_manager
from backend.core.openapi import build_custom_openapi
from backend.database.database_manager import get_database_manager
from backend.utils.logger import get_logger


# 初始化日志
logger = get_logger(__name__)

# 全局配置管理器实例（避免重复加载）
_config_manager = None


def get_cached_config_manager():
    """
    获取缓存的配置管理器实例

    Returns:
        ConfigManager实例
    """
    global _config_manager
    if _config_manager is None:
        _config_manager = get_config_manager()
    return _config_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理

    启动时：
    1. 加载配置
    2. 初始化数据库连接
    3. 验证配置完整性
    4. 记录启动日志

    关闭时：
    1. 关闭数据库连接
    2. 清理资源
    3. 记录关闭日志
    """
    # 启动事件
    logger.info("=" * 80)
    logger.info("正在启动个人智能体系统...")
    logger.info("=" * 80)

    try:
        # 1. 加载配置
        config_manager = get_cached_config_manager()
        logger.info("配置加载成功")

        # 2. 验证配置
        if not config_manager.validate_config():
            logger.error("配置验证失败")
            raise RuntimeError("配置无效")

        # 3. 初始化数据库连接
        db_manager = get_database_manager()
        if db_manager.test_connection():
            logger.info("数据库连接建立成功")
        else:
            logger.error("数据库连接失败")
            raise RuntimeError("数据库连接失败")

        # 4. 记录配置信息
        api_config = config_manager.get_business_config("api")
        logger.info(f"API主机: {api_config.get('host', '0.0.0.0')}")
        logger.info(f"API端口: {api_config.get('port', 8000)}")
        logger.info(f"调试模式: {api_config.get('debug', False)}")

        # 5. 初始化所有工具（包括本地工具和MCP工具）
        # 工具会在tool_initializer模块导入时自动初始化
        from backend.tools import tool_initializer
        logger.info("所有工具初始化成功（本地工具和MCP工具）")

        logger.info("=" * 80)
        logger.info("个人智能体系统启动成功")
        logger.info("=" * 80)

        yield

    except Exception as e:
        logger.error(f"应用启动失败: {str(e)}", exc_info=True)
        raise

    # 关闭事件
    logger.info("=" * 80)
    logger.info("正在关闭个人智能体系统...")
    logger.info("=" * 80)

    # 独立关闭每个资源，确保即使某个资源关闭失败，其他资源也能正常关闭
    # 1. 安全关闭MCP工具的HTTP会话
    try:
        from backend.tools.tool_registry import get_all_tools
        from backend.tools.mcp.base_mcp_tool import MCPTool

        all_tools = get_all_tools()
        for tool_name, tool_instance in all_tools.items():
            if isinstance(tool_instance, MCPTool):
                await tool_instance.close()
        logger.info("MCP工具HTTP会话已关闭")
    except Exception as e:
        logger.error(f"MCP工具关闭失败: {str(e)}", exc_info=True)

    # 2. 安全关闭数据库连接
    try:
        db_manager = get_database_manager()
        db_manager.close()
        logger.info("数据库连接已关闭")
    except Exception as e:
        logger.error(f"数据库连接关闭失败: {str(e)}", exc_info=True)

    logger.info("=" * 80)
    logger.info("个人智能体系统关闭完成")
    logger.info("=" * 80)


# 创建FastAPI应用实例
app = FastAPI(
    title="Personal Agent System",
    description="企业级多Agent知识库助手系统",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
    # 使用国内CDN加速Swagger UI资源加载
    swagger_ui_parameters={
        "syntaxHighlight.theme": "monokai",
        "docExpansion": "none",
        "defaultModelsExpandDepth": -1,
    },
    # 使用国内CDN
    swagger_favicon_url="https://fastapi.tiangolo.com/img/favicon.png"
)
app.openapi = lambda: build_custom_openapi(app)


# 立即配置CORS中间件（必须在其他中间件之前）
# 从配置文件读取CORS设置，支持开发和生产环境
config_manager = get_cached_config_manager()
api_config = config_manager.get_business_config("api")
cors_config = api_config.get("cors", {})
allow_origins = cors_config.get("allow_origins", ["http://localhost:3000"])
allow_origin_regex = cors_config.get("allow_origin_regex", r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=cors_config.get("allow_credentials", True),
    allow_methods=cors_config.get("allow_methods", ["GET", "POST", "PUT", "DELETE", "OPTIONS"]),
    allow_headers=cors_config.get("allow_headers", ["*"]),
    expose_headers=["*"],
    max_age=3600,
)
logger.info(f"CORS中间件已配置，允许的源: {allow_origins}")
logger.info(f"CORS中间件已配置，允许的源正则: {allow_origin_regex}")

app.add_middleware(RequestIDMiddleware)
logger.info("请求ID中间件已配置")


# 配置请求日志中间件
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    记录所有HTTP请求

    Args:
        request: HTTP请求
        call_next: 下一个中间件

    Returns:
        HTTP响应
    """
    # 记录请求信息
    logger.info(
        f"请求: {request.method} {request.url.path} "
        f"来自 {request.client.host if request.client else '未知'}"
    )

    # 处理请求
    try:
        response = await call_next(request)

        # 记录响应信息
        logger.info(
            f"响应: {request.method} {request.url.path} "
            f"状态码={response.status_code}"
        )

        return response

    except Exception as e:
        logger.error(
            f"请求失败: {request.method} {request.url.path} "
            f"错误={str(e)}",
            exc_info=True
        )
        raise


# 全局异常处理器
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    处理HTTP异常

    Args:
        request: HTTP请求
        exc: HTTP异常

    Returns:
        错误响应
    """
    logger.warning(
        f"HTTP异常: {request.method} {request.url.path} "
        f"状态码={exc.status_code} 详情={exc.detail}"
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse.create(
            code=exc.status_code,
            message=exc.detail,
            error="HTTPException",
            error_code=infer_error_code(request.url.path, exc.status_code, str(exc.detail)),
        ).model_dump()
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    处理请求验证异常

    Args:
        request: HTTP请求
        exc: 验证异常

    Returns:
        错误响应
    """
    logger.warning(
        f"验证错误: {request.method} {request.url.path} "
        f"错误={exc.errors()}"
    )

    # 转换验证错误为错误详情列表
    error_details = [
        ErrorDetail(
            field=".".join(str(loc) for loc in error.get("loc", [])),
            message=error.get("msg", ""),
            type=error.get("type", "")
        )
        for error in exc.errors()
    ]

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse.create(
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message="请求验证失败",
            error="ValidationError",
            error_code=ErrorCode.SYSTEM_VALIDATION_ERROR.value,
            details=error_details
        ).model_dump()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """
    处理未捕获的异常

    Args:
        request: HTTP请求
        exc: 异常

    Returns:
        错误响应
    """
    logger.error(
        f"未处理的异常: {request.method} {request.url.path} "
        f"错误={str(exc)}",
        exc_info=True
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse.create(
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="服务器内部错误",
            error="InternalServerError",
            error_code=ErrorCode.SYSTEM_INTERNAL_ERROR.value,
        ).model_dump()
    )


# 注册路由
def register_routes():
    """注册所有API路由"""
    # 认证路由
    app.include_router(auth.router)
    logger.info("认证路由已注册: /api/v1/auth")

    # 对话路由
    app.include_router(chat.router)
    logger.info("对话路由已注册: /api/v1/chat")

    # 会话管理路由
    app.include_router(conversations.router)
    logger.info("会话管理路由已注册: /api/v1/conversations")

    # 知识库管理路由
    app.include_router(knowledge.router)
    logger.info("知识库路由已注册: /api/v1/knowledge")

    # 工具管理路由
    app.include_router(tools.router)
    logger.info("工具管理路由已注册: /api/v1/tools")

    # 内容生成路由
    app.include_router(content_generation.router)
    logger.info("内容生成路由已注册: /api/v1/content")

    logger.info("=" * 80)
    logger.info("所有API路由注册完成")
    logger.info("=" * 80)


# 根路径端点
@app.get("/", tags=["root"])
async def root():
    """
    根路径端点 - 提供API信息和文档链接

    Returns:
        API信息
    """
    return {
        "name": "Personal Agent System API",
        "version": "1.0.0",
        "description": "企业级多Agent知识库助手系统",
        "status": "running",
        "documentation": {
            "swagger_ui": "/api/docs",
            "redoc": "/api/redoc",
            "openapi_json": "/api/openapi.json"
        },
        "endpoints": {
            "health": "/health",
            "auth": "/api/v1/auth",
            "chat": "/api/v1/chat",
            "conversations": "/api/v1/conversations",
            "knowledge": "/api/v1/knowledge",
            "tools": "/api/v1/tools",
            "content": "/api/v1/content"
        }
    }


# 健康检查端点
@app.get("/health", response_model=MessageResponse, tags=["health"])
async def health_check():
    """
    健康检查端点

    Returns:
        健康状态响应
    """
    try:
        # 检查数据库连接
        db_manager = get_database_manager()
        db_healthy = db_manager.test_connection()

        if db_healthy:
            return MessageResponse.create(
                message="服务运行正常",
                code=200
            )
        else:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content=MessageResponse.create(
                    message="数据库连接失败",
                    code=503
                ).model_dump()
            )

    except Exception as e:
        logger.error(f"健康检查失败: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=MessageResponse.create(
                message=f"健康检查失败: {str(e)}",
                code=503
            ).model_dump()
        )


# 注册路由
register_routes()


def main():
    """
    主函数：启动FastAPI应用

    从配置文件读取启动参数
    """
    try:
        # 使用缓存的配置管理器
        config_manager = get_cached_config_manager()
        api_config = config_manager.get_business_config("api")

        # 获取启动参数
        host = api_config.get("host", "0.0.0.0")
        port = api_config.get("port", 8000)
        debug = api_config.get("debug", False)
        reload = api_config.get("reload", True)

        # 启动服务
        logger.info(f"正在启动服务器: {host}:{port}")

        uvicorn.run(
            "backend.main:app",
            host=host,
            port=port,
            reload=reload,
            log_level="info" if not debug else "debug"
        )

    except Exception as e:
        logger.error(f"服务器启动失败: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
