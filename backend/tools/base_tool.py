"""工具体系基础抽象定义。

本文件是整个工具系统的基础层，主要提供三类能力：
1. 统一的工具异常类型，便于上层分类处理失败场景。
2. 工具参数与工具定义的数据结构，作为工具输入输出契约的标准表达。
3. ``BaseTool`` 抽象基类，为所有具体工具提供统一接口和公共执行流程。

设计目的：
- 让不同工具具备一致的注册、校验、执行和超时控制方式。
- 让工具定义可以被统一序列化，供 Agent 或其他调用方消费。
- 将日志、参数校验、异常兜底等通用逻辑下沉，减少重复实现。
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Dict, List, Optional


class ToolError(Exception):
    """所有工具异常的基类。"""

    default_error_code = "TOOL_ERROR"
    default_error_type = "tool_error"

    def __init__(
        self,
        message: str = "",
        *,
        error_code: Optional[str] = None,
        error_type: Optional[str] = None,
    ):
        super().__init__(message)
        self.error_code = error_code or self.default_error_code
        self.error_type = error_type or self.default_error_type


class ToolTimeoutError(ToolError):
    """表示工具执行超时。"""

    default_error_code = "TOOL_TIMEOUT"
    default_error_type = "timeout"


class ToolParameterError(ToolError):
    """表示工具参数不合法。"""

    default_error_code = "TOOL_INVALID_PARAMETER"
    default_error_type = "parameter_error"


class ToolExecutionError(ToolError):
    """表示工具内部执行逻辑失败。"""

    default_error_code = "TOOL_EXECUTION_ERROR"
    default_error_type = "execution_error"


class ToolConfigurationError(ToolError):
    """表示工具运行依赖的配置缺失或不合法。"""

    default_error_code = "TOOL_CONFIGURATION_ERROR"
    default_error_type = "configuration_error"


class ToolNetworkError(ToolError):
    """表示工具访问外部网络资源时发生异常。"""

    default_error_code = "TOOL_NETWORK_ERROR"
    default_error_type = "network_error"


@dataclass
class ToolParameter:
    """单个工具参数的标准描述对象。"""

    name: str
    type: str  # string, number, integer, boolean, array, object
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[Any]] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None
    items: Optional[dict[str, Any]] = None
    properties: Optional[dict[str, Any]] = None
    additional_properties: Optional[bool] = None

    def to_json_schema(self) -> dict[str, Any]:
        """将当前参数定义转换为 JSON Schema 片段。"""

        schema: dict[str, Any] = {
            "type": self.type,
            "description": self.description,
        }

        if self.enum:
            schema["enum"] = self.enum
        if self.default is not None:
            schema["default"] = self.default
        if self.minimum is not None:
            schema["minimum"] = self.minimum
        if self.maximum is not None:
            schema["maximum"] = self.maximum
        if self.min_length is not None:
            schema["minLength"] = self.min_length
        if self.max_length is not None:
            schema["maxLength"] = self.max_length
        if self.pattern is not None:
            schema["pattern"] = self.pattern
        if self.items is not None:
            schema["items"] = self.items
        if self.properties is not None:
            schema["properties"] = self.properties
        if self.additional_properties is not None:
            schema["additionalProperties"] = self.additional_properties

        return schema


@dataclass
class ToolDefinition:
    """工具元信息定义。"""

    name: str
    description: str
    parameters: List[ToolParameter]
    category: str = "general"
    version: str = "1.0.0"
    timeout: int = 30
    strict_validation: bool = False

    def to_dict(self) -> dict[str, Any]:
        """将工具定义转换为标准字典结构。"""

        properties = {}
        required = []
        for param in self.parameters:
            properties[param.name] = param.to_json_schema()
            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "version": self.version,
            "timeout": self.timeout,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": not self.strict_validation,
            },
        }

    @property
    def input_schema(self) -> dict[str, Any]:
        return self.to_dict()["parameters"]

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {},
                "error": {"type": ["string", "null"]},
                "error_code": {"type": ["string", "null"]},
                "error_type": {"type": ["string", "null"]},
                "metadata": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
            "required": ["success", "data", "error", "error_code", "error_type", "metadata"],
            "additionalProperties": True,
        }


class BaseTool(ABC):
    """所有具体工具都必须继承的抽象基类。"""

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._definition = self._create_definition()

    @abstractmethod
    def _create_definition(self) -> ToolDefinition:
        """由子类返回自身的工具定义。"""

    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """由子类实现实际业务执行逻辑。"""

    def _validate_value(self, param: ToolParameter, value: Any) -> Optional[str]:
        if value is None:
            if param.required:
                return f"参数 {param.name} 不能为空"
            return None

        if param.type == "string":
            if not isinstance(value, str):
                return f"参数 {param.name} 必须是字符串类型"
            if param.min_length is not None and len(value) < param.min_length:
                return f"参数 {param.name} 长度不能少于 {param.min_length}"
            if param.max_length is not None and len(value) > param.max_length:
                return f"参数 {param.name} 长度不能超过 {param.max_length}"
        elif param.type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return f"参数 {param.name} 必须是数字类型"
        elif param.type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                return f"参数 {param.name} 必须是整数类型"
        elif param.type == "boolean":
            if not isinstance(value, bool):
                return f"参数 {param.name} 必须是布尔类型"
        elif param.type == "array":
            if not isinstance(value, list):
                return f"参数 {param.name} 必须是数组类型"
            if param.items:
                expected_item_type = param.items.get("type")
                if expected_item_type:
                    for index, item in enumerate(value):
                        if not self._matches_type(item, expected_item_type):
                            return f"参数 {param.name}[{index}] 必须是 {expected_item_type} 类型"
        elif param.type == "object":
            if not isinstance(value, dict):
                return f"参数 {param.name} 必须是对象类型"
            if param.properties:
                for property_name, property_schema in param.properties.items():
                    if property_name not in value:
                        continue
                    property_type = property_schema.get("type")
                    if property_type and not self._matches_type(value[property_name], property_type):
                        return f"参数 {param.name}.{property_name} 必须是 {property_type} 类型"
                if param.additional_properties is False:
                    allowed_keys = set(param.properties.keys())
                    extra_keys = set(value.keys()) - allowed_keys
                    if extra_keys:
                        return f"参数 {param.name} 包含未声明字段: {sorted(extra_keys)}"

        if param.enum and value not in param.enum:
            return f"参数 {param.name} 的值必须是以下之一: {param.enum}"

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if param.minimum is not None and value < param.minimum:
                return f"参数 {param.name} 不能小于 {param.minimum}"
            if param.maximum is not None and value > param.maximum:
                return f"参数 {param.name} 不能大于 {param.maximum}"

        return None

    @staticmethod
    def _matches_type(value: Any, expected_type: str) -> bool:
        type_mapping = {
            "string": lambda item: isinstance(item, str),
            "number": lambda item: not isinstance(item, bool) and isinstance(item, (int, float)),
            "integer": lambda item: not isinstance(item, bool) and isinstance(item, int),
            "boolean": lambda item: isinstance(item, bool),
            "array": lambda item: isinstance(item, list),
            "object": lambda item: isinstance(item, dict),
        }
        checker = type_mapping.get(expected_type)
        return checker(value) if checker else True

    def validate_parameters(self, **kwargs) -> tuple[bool, Optional[str]]:
        """校验传入参数是否合法。"""

        parameter_definitions = {param.name: param for param in self._definition.parameters}

        for param in self._definition.parameters:
            if param.required and param.name not in kwargs:
                return False, f"缺少必需参数: {param.name}"

        if self._definition.strict_validation:
            extra_keys = set(kwargs.keys()) - set(parameter_definitions.keys())
            if extra_keys:
                return False, f"存在未声明参数: {sorted(extra_keys)}"

        for name, value in kwargs.items():
            param = parameter_definitions.get(name)
            if param is None:
                continue
            error = self._validate_value(param, value)
            if error:
                return False, error

        return True, None

    def _apply_parameter_defaults(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        resolved = dict(kwargs)
        for param in self._definition.parameters:
            if param.name not in resolved and param.default is not None:
                resolved[param.name] = param.default
        return resolved

    def _build_result(
        self,
        *,
        success: bool,
        data: Any = None,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
        error_type: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        **extra_fields: Any,
    ) -> Dict[str, Any]:
        normalized_metadata = dict(metadata or {})
        normalized_metadata.setdefault("tool_name", self.get_name())
        result: Dict[str, Any] = {
            "success": success,
            "data": data,
            "error": error,
            "error_code": error_code,
            "error_type": error_type,
            "metadata": normalized_metadata,
        }
        result.update(extra_fields)
        return result

    def _normalize_result(self, result: Any, duration_ms: int) -> Dict[str, Any]:
        if not isinstance(result, dict):
            result = {"success": True, "data": result}

        normalized = self._build_result(
            success=bool(result.get("success", True)),
            data=result.get("data"),
            error=result.get("error"),
            error_code=result.get("error_code"),
            error_type=result.get("error_type"),
            metadata=result.get("metadata") if isinstance(result.get("metadata"), dict) else {},
        )

        for key, value in result.items():
            if key not in normalized:
                normalized[key] = value

        normalized["metadata"]["duration_ms"] = duration_ms

        if normalized["success"]:
            normalized["error"] = None
            normalized["error_code"] = None
            normalized["error_type"] = None
        else:
            normalized["error"] = normalized["error"] or "工具执行失败"
            normalized["error_code"] = normalized["error_code"] or ToolExecutionError.default_error_code
            normalized["error_type"] = normalized["error_type"] or ToolExecutionError.default_error_type

        return normalized

    def get_definition(self) -> ToolDefinition:
        return self._definition

    def get_name(self) -> str:
        return self._definition.name

    def get_description(self) -> str:
        return self._definition.description

    def get_category(self) -> str:
        return self._definition.category

    def get_transport_protocol(self) -> str:
        return "direct"

    def get_tool_origin(self) -> str:
        return "local"

    def get_mcp_server(self) -> Optional[str]:
        return None

    @property
    def name(self) -> str:
        return self.get_name()

    @property
    def description(self) -> str:
        return self.get_description()

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._definition.input_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return self._definition.output_schema

    @property
    def timeout(self) -> int:
        return self._definition.timeout

    @timeout.setter
    def timeout(self, value: int) -> None:
        self._definition.timeout = value

    async def invoke(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.safe_execute(**payload)

    async def _execute_with_validation(self, **kwargs) -> Dict[str, Any]:
        prepared_kwargs = self._apply_parameter_defaults(kwargs)
        is_valid, error_msg = self.validate_parameters(**prepared_kwargs)
        if not is_valid:
            raise ToolParameterError(error_msg or "工具参数不合法")

        self.logger.info("开始执行工具: %s", self.get_name())
        return await self.execute(**prepared_kwargs)

    async def safe_execute(self, **kwargs) -> Dict[str, Any]:
        """带超时与异常保护的执行入口。"""

        timeout = kwargs.pop("timeout", None) or self._definition.timeout
        started_at = perf_counter()

        try:
            result = await asyncio.wait_for(
                self._execute_with_validation(**kwargs),
                timeout=timeout,
            )
            duration_ms = int((perf_counter() - started_at) * 1000)
            normalized = self._normalize_result(result, duration_ms)
            self.logger.info("工具执行完成: %s, success=%s", self.get_name(), normalized["success"])
            return normalized
        except asyncio.TimeoutError:
            duration_ms = int((perf_counter() - started_at) * 1000)
            self.logger.error("工具执行超时: %s, 超时时间: %s秒", self.get_name(), timeout)
            return self._build_result(
                success=False,
                data=None,
                error=f"工具执行超时（{timeout}秒）",
                error_code=ToolTimeoutError.default_error_code,
                error_type=ToolTimeoutError.default_error_type,
                metadata={"timeout": timeout, "duration_ms": duration_ms},
            )
        except ToolError as exc:
            duration_ms = int((perf_counter() - started_at) * 1000)
            self.logger.error("工具执行失败: %s", str(exc), exc_info=True)
            return self._build_result(
                success=False,
                data=None,
                error=str(exc),
                error_code=getattr(exc, "error_code", ToolExecutionError.default_error_code),
                error_type=getattr(exc, "error_type", ToolExecutionError.default_error_type),
                metadata={"duration_ms": duration_ms},
            )
        except Exception as exc:
            duration_ms = int((perf_counter() - started_at) * 1000)
            self.logger.error("工具执行失败: %s", str(exc), exc_info=True)
            return self._build_result(
                success=False,
                data=None,
                error=f"工具执行失败: {str(exc)}",
                error_code=ToolExecutionError.default_error_code,
                error_type=ToolExecutionError.default_error_type,
                metadata={"duration_ms": duration_ms},
            )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.get_name()}')>"
