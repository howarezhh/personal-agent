"""
Prometheus指标收集器
用于收集和暴露应用程序指标
"""

from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Request, Response
from typing import Callable
import time
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# ============================================
# 定义指标
# ============================================

# 请求计数器
http_requests_total = Counter(
    'http_requests_total',
    'HTTP请求总数',
    ['method', 'endpoint', 'status']
)

# 请求延迟直方图
http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP请求延迟（秒）',
    ['method', 'endpoint']
)

# 活跃请求数
http_requests_in_progress = Gauge(
    'http_requests_in_progress',
    '进行中的HTTP请求数',
    ['method', 'endpoint']
)

# Agent执行计数器
agent_executions_total = Counter(
    'agent_executions_total',
    '智能体执行总数',
    ['agent_name', 'agent_type', 'status']
)

# Agent执行延迟
agent_execution_duration_seconds = Histogram(
    'agent_execution_duration_seconds',
    '智能体执行时长（秒）',
    ['agent_name', 'agent_type']
)

# LLM调用计数器
llm_calls_total = Counter(
    'llm_calls_total',
    'LLM API调用总数',
    ['model', 'provider', 'status']
)

# LLM Token使用量
llm_tokens_used = Counter(
    'llm_tokens_used',
    'Token使用总量',
    ['model', 'provider', 'token_type']  # token_type: prompt/completion
)

# 数据库查询计数器
database_queries_total = Counter(
    'database_queries_total',
    '数据库查询总数',
    ['operation', 'table', 'status']
)

# 数据库查询延迟
database_query_duration_seconds = Histogram(
    'database_query_duration_seconds',
    '数据库查询时长（秒）',
    ['operation', 'table']
)

# 向量数据库操作计数器
vector_db_operations_total = Counter(
    'vector_db_operations_total',
    '向量数据库操作总数',
    ['operation', 'status']
)

# 文件处理计数器
file_processing_total = Counter(
    'file_processing_total',
    '文件处理操作总数',
    ['file_type', 'status']
)

# 文件处理延迟
file_processing_duration_seconds = Histogram(
    'file_processing_duration_seconds',
    '文件处理时长（秒）',
    ['file_type']
)

# 缓存命中率
cache_hits_total = Counter(
    'cache_hits_total',
    '缓存命中总数',
    ['cache_type']
)

cache_misses_total = Counter(
    'cache_misses_total',
    '缓存未命中总数',
    ['cache_type']
)

# 错误计数器
errors_total = Counter(
    'errors_total',
    '错误总数',
    ['error_type', 'component']
)

# 系统信息
system_info = Info(
    'system',
    '系统信息'
)

# 活跃用户数
active_users = Gauge(
    'active_users',
    '活跃用户数'
)

# 活跃会话数
active_conversations = Gauge(
    'active_conversations',
    '活跃会话数'
)


# ============================================
# 指标收集函数
# ============================================

def record_http_request(method: str, endpoint: str, status: int, duration: float):
    """
    记录HTTP请求指标

    Args:
        method: HTTP方法
        endpoint: 端点路径
        status: 状态码
        duration: 请求时长（秒）
    """
    http_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
    http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)
    logger.debug(f"记录HTTP请求指标: {method} {endpoint} - 状态码:{status}, 耗时:{duration:.3f}秒")


def record_agent_execution(
    agent_name: str,
    agent_type: str,
    status: str,
    duration: float
):
    """
    记录Agent执行指标

    Args:
        agent_name: Agent名称
        agent_type: Agent类型
        status: 执行状态
        duration: 执行时长（秒）
    """
    agent_executions_total.labels(
        agent_name=agent_name,
        agent_type=agent_type,
        status=status
    ).inc()
    agent_execution_duration_seconds.labels(
        agent_name=agent_name,
        agent_type=agent_type
    ).observe(duration)
    logger.debug(f"记录智能体执行指标: {agent_name}({agent_type}) - 状态:{status}, 耗时:{duration:.3f}秒")


def record_llm_call(
    model: str,
    provider: str,
    status: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0
):
    """
    记录LLM调用指标

    Args:
        model: 模型名称
        provider: 提供商
        status: 调用状态
        prompt_tokens: 提示词Token数
        completion_tokens: 完成Token数
    """
    llm_calls_total.labels(model=model, provider=provider, status=status).inc()

    if prompt_tokens > 0:
        llm_tokens_used.labels(
            model=model,
            provider=provider,
            token_type='prompt'
        ).inc(prompt_tokens)

    if completion_tokens > 0:
        llm_tokens_used.labels(
            model=model,
            provider=provider,
            token_type='completion'
        ).inc(completion_tokens)

    total_tokens = prompt_tokens + completion_tokens
    logger.debug(f"记录LLM调用指标: {provider}/{model} - 状态:{status}, Token数:{total_tokens}(提示:{prompt_tokens}, 完成:{completion_tokens})")


def record_database_query(
    operation: str,
    table: str,
    status: str,
    duration: float
):
    """
    记录数据库查询指标

    Args:
        operation: 操作类型（SELECT/INSERT/UPDATE/DELETE）
        table: 表名
        status: 执行状态
        duration: 执行时长（秒）
    """
    database_queries_total.labels(
        operation=operation,
        table=table,
        status=status
    ).inc()
    database_query_duration_seconds.labels(
        operation=operation,
        table=table
    ).observe(duration)
    logger.debug(f"记录数据库查询指标: {operation} {table} - 状态:{status}, 耗时:{duration:.3f}秒")


def record_vector_db_operation(operation: str, status: str):
    """
    记录向量数据库操作指标

    Args:
        operation: 操作类型（add/search/delete）
        status: 执行状态
    """
    vector_db_operations_total.labels(operation=operation, status=status).inc()
    logger.debug(f"记录向量数据库操作指标: {operation} - 状态:{status}")


def record_file_processing(file_type: str, status: str, duration: float):
    """
    记录文件处理指标

    Args:
        file_type: 文件类型
        status: 处理状态
        duration: 处理时长（秒）
    """
    file_processing_total.labels(file_type=file_type, status=status).inc()
    file_processing_duration_seconds.labels(file_type=file_type).observe(duration)
    logger.debug(f"记录文件处理指标: {file_type} - 状态:{status}, 耗时:{duration:.3f}秒")


def record_cache_hit(cache_type: str):
    """
    记录缓存命中

    Args:
        cache_type: 缓存类型
    """
    cache_hits_total.labels(cache_type=cache_type).inc()
    logger.debug(f"记录缓存命中: {cache_type}")


def record_cache_miss(cache_type: str):
    """
    记录缓存未命中

    Args:
        cache_type: 缓存类型
    """
    cache_misses_total.labels(cache_type=cache_type).inc()
    logger.debug(f"记录缓存未命中: {cache_type}")


def record_error(error_type: str, component: str):
    """
    记录错误

    Args:
        error_type: 错误类型
        component: 组件名称
    """
    errors_total.labels(error_type=error_type, component=component).inc()
    logger.warning(f"记录错误: {component}组件发生{error_type}错误")


def set_system_info(version: str, environment: str, python_version: str):
    """
    设置系统信息

    Args:
        version: 应用版本
        environment: 运行环境
        python_version: Python版本
    """
    system_info.info({
        'version': version,
        'environment': environment,
        'python_version': python_version
    })
    logger.info(f"设置系统信息: 版本={version}, 环境={environment}, Python={python_version}")


def set_active_users(count: int):
    """
    设置活跃用户数

    Args:
        count: 用户数
    """
    active_users.set(count)
    logger.debug(f"更新活跃用户数: {count}")


def set_active_conversations(count: int):
    """
    设置活跃会话数

    Args:
        count: 会话数
    """
    active_conversations.set(count)
    logger.debug(f"更新活跃会话数: {count}")


# ============================================
# 中间件
# ============================================

async def metrics_middleware(request: Request, call_next: Callable):
    """
    Prometheus指标收集中间件

    Args:
        request: FastAPI请求对象
        call_next: 下一个中间件或路由处理器

    Returns:
        响应对象
    """
    method = request.method
    endpoint = request.url.path

    # 增加进行中的请求数
    http_requests_in_progress.labels(method=method, endpoint=endpoint).inc()

    start_time = time.time()
    status_code = 500  # 默认状态码

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception as e:
        logger.error(f"请求处理失败: {str(e)}")
        record_error(type(e).__name__, "http_request")
        raise
    finally:
        # 减少进行中的请求数
        http_requests_in_progress.labels(method=method, endpoint=endpoint).dec()

        # 记录请求指标
        duration = time.time() - start_time
        record_http_request(method, endpoint, status_code, duration)


# ============================================
# 指标端点
# ============================================

async def metrics_endpoint():
    """
    Prometheus指标端点

    Returns:
        指标数据
    """
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
