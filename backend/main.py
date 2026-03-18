"""FastAPI application entrypoint for the backend service."""

import sys
from contextlib import asynccontextmanager

from backend.core.env_loader import load_environment

load_environment()

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api import auth, chat, content_generation, conversations, knowledge, tools
from backend.api.error_handlers import register_exception_handlers
from backend.api.middleware import RequestIDMiddleware
from backend.application.services.runtime_application_service import RuntimeApplicationService
from backend.contracts.responses import MessageResponse
from backend.core.openapi import build_custom_openapi
from backend.utils.logger import get_logger


logger = get_logger(__name__)
runtime_service = RuntimeApplicationService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    started = False
    try:
        runtime_service.startup()
        started = True
        yield
    except Exception as error:
        logger.error("Application startup failed: %s", error, exc_info=True)
        raise
    finally:
        if started:
            await runtime_service.shutdown()


app = FastAPI(
    title="Personal Agent System",
    description="Enterprise multi-agent knowledge assistant backend",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
    swagger_ui_parameters={
        "syntaxHighlight.theme": "monokai",
        "docExpansion": "none",
        "defaultModelsExpandDepth": -1,
    },
    swagger_favicon_url="https://fastapi.tiangolo.com/img/favicon.png",
)
app.openapi = lambda: build_custom_openapi(app)

cors_config = runtime_service.get_cors_config()
app.add_middleware(CORSMiddleware, **cors_config)
logger.info("CORS middleware configured, allowed origins: %s", cors_config["allow_origins"])
logger.info("CORS middleware configured, allowed origin regex: %s", cors_config["allow_origin_regex"])

app.add_middleware(RequestIDMiddleware)
logger.info("Request ID middleware configured")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(
        "Request: %s %s from %s",
        request.method,
        request.url.path,
        request.client.host if request.client else "unknown",
    )
    try:
        response = await call_next(request)
        logger.info("Response: %s %s status=%s", request.method, request.url.path, response.status_code)
        return response
    except Exception as error:
        logger.error("Request failed: %s %s error=%s", request.method, request.url.path, error, exc_info=True)
        raise


ROUTERS = (
    (auth.router, "/api/v1/auth", "auth"),
    (chat.router, "/api/v1/chat", "chat"),
    (conversations.router, "/api/v1/conversations", "conversations"),
    (knowledge.router, "/api/v1/knowledge", "knowledge"),
    (tools.router, "/api/v1/tools", "tools"),
    (content_generation.router, "/api/v1/content", "content"),
)


def register_routes() -> None:
    for router, prefix, label in ROUTERS:
        app.include_router(router)
        logger.info("Route registered: %s -> %s", label, prefix)
    logger.info("=" * 80)
    logger.info("All API routes registered")
    logger.info("=" * 80)


@app.get("/", tags=["root"])
async def root():
    return runtime_service.get_root_payload()


@app.get("/health", response_model=MessageResponse, tags=["health"])
async def health_check():
    health_status = runtime_service.get_health_status()
    if health_status["healthy"]:
        return MessageResponse.create(message=health_status["message"], code=health_status["code"])
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=MessageResponse.create(
            message=health_status["message"],
            code=health_status["code"],
        ).model_dump(),
    )


register_exception_handlers(app)
register_routes()


def main():
    try:
        server_options = runtime_service.get_server_options()
        logger.info("Starting server: %s:%s", server_options["host"], server_options["port"])
        uvicorn.run(
            "backend.main:app",
            host=server_options["host"],
            port=server_options["port"],
            reload=server_options["reload"],
            log_level="debug" if server_options["debug"] else "info",
        )
    except Exception as error:
        logger.error("Server startup failed: %s", error, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
