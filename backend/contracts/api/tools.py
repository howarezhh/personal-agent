from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ToolExecuteRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "parameters": {
                    "text": "Hello, world!",
                    "source_lang": "en",
                    "target_lang": "zh",
                }
            }
        }
    )

    parameters: Dict[str, Any] = Field(..., description="Tool execution parameters")


class ToolParameterInfo(BaseModel):
    name: str = Field(..., description="Parameter name")
    type: str = Field(..., description="Parameter type")
    description: str = Field(..., description="Parameter description")
    required: bool = Field(..., description="Whether the parameter is required")
    default: Any = Field(None, description="Default value")
    enum: Optional[List[Any]] = Field(None, description="Allowed enum values")
    minimum: Optional[float] = Field(None, description="Minimum numeric value")
    maximum: Optional[float] = Field(None, description="Maximum numeric value")
    min_length: Optional[int] = Field(None, description="Minimum string length")
    max_length: Optional[int] = Field(None, description="Maximum string length")
    pattern: Optional[str] = Field(None, description="Regex pattern")
    items: Optional[Dict[str, Any]] = Field(None, description="Array item schema")
    properties: Optional[Dict[str, Any]] = Field(None, description="Object property schema")
    additional_properties: Optional[bool] = Field(None, description="Whether object accepts extra fields")


class ToolInfo(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "translation",
                "description": "Multilingual translation tool",
                "category": "language",
                "capabilities": ["invoke", "local_direct"],
                "transport_protocol": "mcp",
                "tool_origin": "local",
                "mcp_server": "builtin",
                "parameters": [{"name": "text", "type": "string", "description": "Input text", "required": True}],
                "timeout": 30,
            }
        }
    )

    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    category: str = Field(..., description="Business category")
    capabilities: List[str] = Field(default_factory=list, description="Declared tool capabilities")
    transport_protocol: str = Field(..., description="Runtime transport protocol")
    tool_origin: str = Field(..., description="Tool origin")
    mcp_server: Optional[str] = Field(None, description="Bound MCP server")
    parameters: List[ToolParameterInfo] = Field(..., description="Tool parameter definitions")
    timeout: int = Field(..., description="Timeout in seconds")


class ToolCategoryInfo(BaseModel):
    category: str = Field(..., description="Tool category")
    count: int = Field(..., description="Number of tools in the category")
    tools: List[str] = Field(default_factory=list, description="Tool names in the category")


class ToolCategoryListResponse(BaseModel):
    success: bool = Field(True, description="Whether the request succeeded")
    data: List[ToolCategoryInfo] = Field(default_factory=list, description="Visible tool categories")
    total: int = Field(..., description="Number of categories")


class ToolListResponse(BaseModel):
    success: bool = Field(True, description="Whether the request succeeded")
    data: List[ToolInfo] = Field(..., description="Visible tools")
    total: int = Field(..., description="Number of tools")


class ToolDetailResponse(BaseModel):
    success: bool = Field(True, description="Whether the request succeeded")
    data: ToolInfo = Field(..., description="Tool detail payload")


class ToolExecuteResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "data": {"translated_text": "Hello world in another language"},
                "error": None,
                "error_code": None,
                "error_type": None,
                "metadata": {"tool_name": "translation", "execution_id": "exec_xxx", "tool_call_id": "call_xxx"},
            }
        }
    )

    success: bool = Field(..., description="Whether tool execution succeeded")
    data: Any = Field(None, description="Tool result payload")
    error: Optional[str] = Field(None, description="Error message")
    error_code: Optional[str] = Field(None, description="Stable error code")
    error_type: Optional[str] = Field(None, description="Error category")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Execution metadata")
