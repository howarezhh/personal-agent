from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.contracts.errors import AppException, ErrorCode, infer_error_code
from backend.contracts.responses import ErrorDetail, ErrorResponse
from backend.utils.logger import get_logger


logger = get_logger(__name__)


async def app_exception_handler(request: Request, exc: AppException):
    logger.warning(
        "App exception: %s %s status=%s error_code=%s message=%s",
        request.method,
        request.url.path,
        exc.status_code,
        exc.error_code,
        exc.message,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse.create(
            code=exc.status_code,
            message=exc.message,
            error=exc.error,
            error_code=exc.error_code,
            details=exc.details,
        ).model_dump(),
        headers=exc.headers,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    logger.warning(
        "HTTP exception: %s %s status=%s detail=%s",
        request.method,
        request.url.path,
        exc.status_code,
        exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse.create(
            code=exc.status_code,
            message=str(exc.detail),
            error="HTTPException",
            error_code=infer_error_code(request.url.path, exc.status_code, str(exc.detail)),
        ).model_dump(),
        headers=getattr(exc, 'headers', None),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning("Validation error: %s %s errors=%s", request.method, request.url.path, exc.errors())
    error_details = [
        ErrorDetail(
            field=".".join(str(location) for location in error.get("loc", [])),
            message=error.get("msg", ""),
            type=error.get("type", ""),
        )
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse.create(
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message="请求校验失败",
            error="ValidationError",
            error_code=ErrorCode.SYSTEM_VALIDATION_ERROR.value,
            details=error_details,
        ).model_dump(),
    )


async def general_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s %s error=%s", request.method, request.url.path, str(exc), exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse.create(
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="服务器内部错误",
            error="InternalServerError",
            error_code=ErrorCode.SYSTEM_INTERNAL_ERROR.value,
        ).model_dump(),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
