"""
路由聚合模块
统一管理和注册所有API路由
"""

from fastapi import FastAPI
from backend.api import auth, chat, conversations, knowledge, tools, content_generation
from backend.utils.logger import get_logger


logger = get_logger(__name__)


def register_all_routes(app: FastAPI) -> None:
    """
    注册所有API路由到FastAPI应用

    Args:
        app: FastAPI应用实例
    """
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

    logger.info("=" * 60)
    logger.info("所有API路由注册成功")
    logger.info("=" * 60)


def get_route_summary(app: FastAPI) -> dict:
    """
    获取所有路由的摘要信息

    Args:
        app: FastAPI应用实例

    Returns:
        路由摘要字典
    """
    routes_summary = {
        "total_routes": 0,
        "routes_by_tag": {},
        "routes_by_method": {},
        "all_routes": []
    }

    for route in app.routes:
        # 跳过非API路由
        if not hasattr(route, "methods"):
            continue

        routes_summary["total_routes"] += 1

        # 按方法统计
        for method in route.methods:
            if method not in routes_summary["routes_by_method"]:
                routes_summary["routes_by_method"][method] = 0
            routes_summary["routes_by_method"][method] += 1

        # 按标签统计
        if hasattr(route, "tags"):
            for tag in route.tags:
                if tag not in routes_summary["routes_by_tag"]:
                    routes_summary["routes_by_tag"][tag] = 0
                routes_summary["routes_by_tag"][tag] += 1

        # 添加到所有路由列表
        routes_summary["all_routes"].append({
            "path": route.path,
            "methods": list(route.methods),
            "name": route.name,
            "tags": list(route.tags) if hasattr(route, "tags") else []
        })

    return routes_summary


def print_route_summary(app: FastAPI) -> None:
    """
    打印路由摘要信息到日志

    Args:
        app: FastAPI应用实例
    """
    summary = get_route_summary(app)

    logger.info("=" * 60)
    logger.info("API路由摘要")
    logger.info("=" * 60)
    logger.info(f"路由总数: {summary['total_routes']}")

    logger.info("\n按方法分类:")
    for method, count in sorted(summary['routes_by_method'].items()):
        logger.info(f"  {method}: {count}")

    logger.info("\n按标签分类:")
    for tag, count in sorted(summary['routes_by_tag'].items()):
        logger.info(f"  {tag}: {count}")

    logger.info("=" * 60)
