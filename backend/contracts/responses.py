
from datetime import datetime, timezone
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field


T = TypeVar("T")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApiResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "code": 200,
                "message": "success",
                "data": {"key": "value"},
                "timestamp": "2024-01-01T00:00:00+00:00",
            }
        }
    )

    code: int = Field(default=200)
    message: str = Field(default="success")
    data: Optional[T] = None
    timestamp: str = Field(default_factory=utc_now_iso)


class SuccessResponse(ApiResponse[T], Generic[T]):
    @classmethod
    def create(cls, data: Optional[T] = None, message: str = "success", code: int = 200):
        return cls(code=code, message=message, data=data)


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str
    type: str | None = None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "code": 400,
                "message": "Validation error",
                "error": "ValidationError",
                "error_code": "SYSTEM_VALIDATION_ERROR",
                "details": [
                    {"field": "email", "message": "Invalid email", "type": "value_error"}
                ],
                "timestamp": "2024-01-01T00:00:00+00:00",
            }
        }
    )

    code: int
    message: str
    error: str
    error_code: str
    details: Optional[List[ErrorDetail]] = None
    timestamp: str = Field(default_factory=utc_now_iso)

    @classmethod
    def create(
        cls,
        code: int,
        message: str,
        error: str = "Error",
        error_code: str = "SYSTEM_HTTP_ERROR",
        details: Optional[List[ErrorDetail]] = None,
    ):
        return cls(code=code, message=message, error=error, error_code=error_code, details=details)


class PaginationMeta(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_prev: bool

    @classmethod
    def create(cls, total: int, page: int, page_size: int):
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        return cls(
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1,
        )


class PaginatedResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "code": 200,
                "message": "success",
                "data": [{"id": "1"}],
                "pagination": {
                    "total": 100,
                    "page": 1,
                    "page_size": 20,
                    "total_pages": 5,
                    "has_next": True,
                    "has_prev": False,
                },
                "timestamp": "2024-01-01T00:00:00+00:00",
            }
        }
    )

    code: int = 200
    message: str = "success"
    data: List[T] = Field(default_factory=list)
    pagination: PaginationMeta
    timestamp: str = Field(default_factory=utc_now_iso)

    @classmethod
    def create(cls, data: List[T], total: int, page: int, page_size: int, message: str = "success"):
        return cls(data=data, message=message, pagination=PaginationMeta.create(total, page, page_size))


class MessageResponse(BaseModel):
    message: str
    code: int = 200
    timestamp: str = Field(default_factory=utc_now_iso)

    @classmethod
    def create(cls, message: str, code: int = 200):
        return cls(message=message, code=code)

