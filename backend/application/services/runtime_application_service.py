from __future__ import annotations

from typing import Any

from backend.core.config_manager import get_config_manager
from backend.database.database_manager import get_database_manager
from backend.utils.logger import get_logger


class RuntimeApplicationService:
    """Centralize backend startup, shutdown, and runtime config access."""

    def __init__(self) -> None:
        self.logger = get_logger(self.__class__.__name__)

    @staticmethod
    def _get_config_manager():
        return get_config_manager()

    @staticmethod
    def _get_database_manager():
        return get_database_manager()

    @staticmethod
    def _initialize_tools(strict: bool = True) -> dict[str, Any]:
        from backend.tools.tool_initializer import initialize_tools

        return initialize_tools(strict=strict)

    @staticmethod
    async def _close_tool_clients() -> None:
        from backend.tools.tool_initializer import close_initialized_tool_clients

        await close_initialized_tool_clients()

    def get_api_config(self) -> dict[str, Any]:
        return dict(self._get_config_manager().get_business_config("api") or {})

    def get_server_options(self) -> dict[str, Any]:
        api_config = self.get_api_config()
        return {
            "host": api_config.get("host", "0.0.0.0"),
            "port": int(api_config.get("port", 8000)),
            "debug": bool(api_config.get("debug", False)),
            "reload": bool(api_config.get("reload", True)),
        }

    def get_cors_config(self) -> dict[str, Any]:
        cors_config = dict(self.get_api_config().get("cors", {}) or {})
        return {
            "allow_origins": cors_config.get("allow_origins", ["http://localhost:3000"]),
            "allow_origin_regex": cors_config.get(
                "allow_origin_regex",
                r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
            ),
            "allow_credentials": cors_config.get("allow_credentials", True),
            "allow_methods": cors_config.get("allow_methods", ["GET", "POST", "PUT", "DELETE", "OPTIONS"]),
            "allow_headers": cors_config.get("allow_headers", ["*"]),
            "expose_headers": ["*"],
            "max_age": 3600,
        }

    def startup(self) -> dict[str, Any]:
        self.logger.info("=" * 80)
        self.logger.info("Starting Personal Agent backend...")
        self.logger.info("=" * 80)

        config_manager = self._get_config_manager()
        self.logger.info("Configuration loaded")
        if not config_manager.validate_config():
            self.logger.error("Configuration validation failed")
            raise RuntimeError("Invalid configuration")

        db_manager = self._get_database_manager()
        if not db_manager.test_connection():
            self.logger.error("Database connection failed")
            raise RuntimeError("Database connection failed")
        self.logger.info("Database connection established")

        api_config = self.get_api_config()
        self.logger.info("API host: %s", api_config.get("host", "0.0.0.0"))
        self.logger.info("API port: %s", api_config.get("port", 8000))
        self.logger.info("Debug mode: %s", api_config.get("debug", False))

        tool_report = self._initialize_tools(strict=True)
        self.logger.info(
            "Tools initialized: registered=%s, mcp=%s, local=%s, external=%s, failures=%s",
            tool_report.get("registered_count", 0),
            tool_report.get("mcp_transport_count", tool_report.get("mcp_count", 0)),
            tool_report.get("local_origin_count", tool_report.get("local_count", 0)),
            tool_report.get("external_origin_count", 0),
            len(tool_report.get("failures", [])),
        )

        self.logger.info("=" * 80)
        self.logger.info("Backend startup completed")
        self.logger.info("=" * 80)
        return {"api_config": api_config, "tool_report": tool_report}

    async def shutdown(self) -> None:
        self.logger.info("=" * 80)
        self.logger.info("Shutting down Personal Agent backend...")
        self.logger.info("=" * 80)

        try:
            await self._close_tool_clients()
            self.logger.info("Tool clients closed")
        except Exception as error:
            self.logger.error("Tool client shutdown failed: %s", error, exc_info=True)

        try:
            self._get_database_manager().close()
            self.logger.info("Database connection closed")
        except Exception as error:
            self.logger.error("Database shutdown failed: %s", error, exc_info=True)

        self.logger.info("=" * 80)
        self.logger.info("Backend shutdown completed")
        self.logger.info("=" * 80)

    def get_root_payload(self) -> dict[str, Any]:
        return {
            "name": "Personal Agent System API",
            "version": "1.0.0",
            "description": "Enterprise multi-agent knowledge assistant backend",
            "status": "running",
            "documentation": {
                "swagger_ui": "/api/docs",
                "redoc": "/api/redoc",
                "openapi_json": "/api/openapi.json",
            },
            "endpoints": {
                "health": "/health",
                "auth": "/api/v1/auth",
                "chat": "/api/v1/chat",
                "conversations": "/api/v1/conversations",
                "knowledge": "/api/v1/knowledge",
                "tools": "/api/v1/tools",
                "content": "/api/v1/content",
            },
        }

    def get_health_status(self) -> dict[str, Any]:
        try:
            if self._get_database_manager().test_connection():
                return {"healthy": True, "message": "Service is healthy", "code": 200}
            return {"healthy": False, "message": "Database connection failed", "code": 503}
        except Exception as error:
            self.logger.error("Health check failed: %s", error, exc_info=True)
            return {"healthy": False, "message": f"Health check failed: {error}", "code": 503}
