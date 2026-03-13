"""
工具基类
定义所有工具的统一接口和规范
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import logging
import asyncio


# 定义工具错误类型
class ToolError(Exception):
    """工具执行错误基类"""
    pass


class ToolTimeoutError(ToolError):
    """工具执行超时错误"""
    pass


class ToolParameterError(ToolError):
    """工具参数错误"""
    pass


class ToolExecutionError(ToolError):
    """工具执行错误"""
    pass


class ToolNetworkError(ToolError):
    """工具网络错误"""
    pass


@dataclass
class ToolParameter:
    """
    工具参数定义
    """
    name: str
    type: str  # string, number, integer, boolean, array, object
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[Any]] = None  # 枚举值列表

    def to_json_schema(self) -> dict:
        """
        转换为JSON Schema格式

        Returns:
            JSON Schema格式的参数定义
        """
        schema = {
            "type": self.type,
            "description": self.description
        }

        if self.enum:
            schema["enum"] = self.enum

        if self.default is not None:
            schema["default"] = self.default

        return schema


@dataclass
class ToolDefinition:
    """
    工具定义
    包含工具的元数据和参数schema
    """
    name: str
    description: str
    parameters: List[ToolParameter]
    category: str = "general"  # general, search, calculation, data, weather, etc.
    version: str = "1.0.0"  # 工具版本号
    timeout: int = 30  # 默认超时时间（秒）

    def to_dict(self) -> dict:
        """
        转换为字典格式

        Returns:
            工具定义字典
        """
        # 构建参数schema
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
            "timeout": self.timeout,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }

    @property
    def input_schema(self) -> dict:
        return self.to_dict()["parameters"]

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {},
                "error": {"type": ["string", "null"]},
                "metadata": {"type": ["object", "null"]},
            },
            "required": ["success"],
        }


class BaseTool(ABC):
    """
    工具基类

    所有工具必须继承此基类并实现execute方法
    """

    def __init__(self):
        """初始化工具"""
        self.logger = logging.getLogger(self.__class__.__name__)
        self._definition = self._create_definition()

    @abstractmethod
    def _create_definition(self) -> ToolDefinition:
        """
        创建工具定义

        子类必须实现此方法，定义工具的名称、描述和参数

        Returns:
            工具定义对象
        """
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        执行工具

        子类必须实现此方法，执行具体的工具逻辑

        Args:
            **kwargs: 工具参数

        Returns:
            工具执行结果，格式为:
            {
                "success": bool,
                "data": Any,
                "error": Optional[str],
                "metadata": Optional[Dict]
            }
        """
        pass

    def validate_parameters(self, **kwargs) -> tuple[bool, Optional[str]]:
        """
        验证参数

        Args:
            **kwargs: 工具参数

        Returns:
            (是否有效, 错误信息)
        """
        # 检查必需参数
        for param in self._definition.parameters:
            if param.required and param.name not in kwargs:
                return False, f"缺少必需参数: {param.name}"

        # 检查参数类型
        for param in self._definition.parameters:
            if param.name in kwargs:
                value = kwargs[param.name]

                # 类型检查
                if param.type == "string" and not isinstance(value, str):
                    return False, f"参数 {param.name} 必须是字符串类型"
                elif param.type == "number" and (
                    isinstance(value, bool) or not isinstance(value, (int, float))
                ):
                    return False, f"参数 {param.name} 必须是数字类型"
                elif param.type == "integer" and (
                    isinstance(value, bool) or not isinstance(value, int)
                ):
                    return False, f"参数 {param.name} 必须是整数类型"
                elif param.type == "boolean" and not isinstance(value, bool):
                    return False, f"参数 {param.name} 必须是布尔类型"
                elif param.type == "array" and not isinstance(value, list):
                    return False, f"参数 {param.name} 必须是数组类型"
                elif param.type == "object" and not isinstance(value, dict):
                    return False, f"参数 {param.name} 必须是对象类型"

                # 枚举值检查
                if param.enum and value not in param.enum:
                    return False, f"参数 {param.name} 的值必须是以下之一: {param.enum}"

        return True, None

    def get_definition(self) -> ToolDefinition:
        """
        获取工具定义

        Returns:
            工具定义对象
        """
        return self._definition

    def get_name(self) -> str:
        """
        获取工具名称

        Returns:
            工具名称
        """
        return self._definition.name

    def get_description(self) -> str:
        """
        获取工具描述

        Returns:
            工具描述
        """
        return self._definition.description

    def get_category(self) -> str:
        """
        获取工具分类

        Returns:
            工具分类
        """
        return self._definition.category

    @property
    def name(self) -> str:
        return self.get_name()

    @property
    def description(self) -> str:
        return self.get_description()

    @property
    def input_schema(self) -> dict:
        return self._definition.input_schema

    @property
    def output_schema(self) -> dict:
        return self._definition.output_schema

    @property
    def timeout(self) -> int:
        return self._definition.timeout

    @timeout.setter
    def timeout(self, value: int) -> None:
        self._definition.timeout = value

    async def invoke(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.safe_execute(**payload)

    async def safe_execute(self, **kwargs) -> Dict[str, Any]:
        """
        安全执行工具（带参数验证、异常处理和超时控制）

        Args:
            **kwargs: 工具参数（可包含timeout参数指定超时时间）

        Returns:
            工具执行结果
        """
        # 获取超时时间（优先使用参数中的timeout，否则使用工具定义的默认值）
        timeout = kwargs.pop('timeout', None) or self._definition.timeout

        try:
            # 使用asyncio.wait_for添加超时控制
            result = await asyncio.wait_for(
                self._execute_with_validation(**kwargs),
                timeout=timeout
            )
            return result

        except asyncio.TimeoutError:
            self.logger.error(f"工具执行超时: {self.get_name()}, 超时时间: {timeout}秒")
            return {
                "success": False,
                "data": None,
                "error": f"工具执行超时（{timeout}秒）",
                "error_type": "timeout",
                "metadata": {
                    "tool_name": self.get_name(),
                    "timeout": timeout
                }
            }
        except ToolTimeoutError as e:
            self.logger.error(f"工具执行超时: {str(e)}")
            return {
                "success": False,
                "data": None,
                "error": str(e),
                "error_type": "timeout",
                "metadata": {"tool_name": self.get_name()}
            }
        except ToolParameterError as e:
            self.logger.error(f"工具参数错误: {str(e)}")
            return {
                "success": False,
                "data": None,
                "error": str(e),
                "error_type": "parameter_error",
                "metadata": {"tool_name": self.get_name()}
            }
        except ToolNetworkError as e:
            self.logger.error(f"工具网络错误: {str(e)}")
            return {
                "success": False,
                "data": None,
                "error": str(e),
                "error_type": "network_error",
                "metadata": {"tool_name": self.get_name()}
            }
        except ToolExecutionError as e:
            self.logger.error(f"工具执行错误: {str(e)}")
            return {
                "success": False,
                "data": None,
                "error": str(e),
                "error_type": "execution_error",
                "metadata": {"tool_name": self.get_name()}
            }
        except Exception as e:
            self.logger.error(f"工具执行失败: {str(e)}", exc_info=True)
            return {
                "success": False,
                "data": None,
                "error": f"工具执行失败: {str(e)}",
                "error_type": "unknown",
                "metadata": {"tool_name": self.get_name()}
            }

    async def _execute_with_validation(self, **kwargs) -> Dict[str, Any]:
        """
        带参数验证的执行方法（内部使用）

        Args:
            **kwargs: 工具参数

        Returns:
            工具执行结果
        """
        try:
            # 验证参数
            is_valid, error_msg = self.validate_parameters(**kwargs)
            if not is_valid:
                self.logger.error(f"参数验证失败: {error_msg}")
                return {
                    "success": False,
                    "data": None,
                    "error": error_msg,
                    "metadata": {"tool_name": self.get_name()}
                }

            # 执行工具
            self.logger.info(f"开始执行工具: {self.get_name()}, 参数: {kwargs}")
            result = await self.execute(**kwargs)

            # 确保返回格式正确
            if not isinstance(result, dict):
                result = {"success": True, "data": result}

            if "success" not in result:
                result["success"] = True

            if "metadata" not in result:
                result["metadata"] = {}

            result["metadata"]["tool_name"] = self.get_name()

            self.logger.info(f"工具执行完成: {self.get_name()}")
            return result

        except Exception as e:
            self.logger.error(f"工具执行失败: {str(e)}", exc_info=True)
            return {
                "success": False,
                "data": None,
                "error": f"工具执行失败: {str(e)}",
                "metadata": {"tool_name": self.get_name()}
            }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.get_name()}')>"
