
from typing import Dict, Any
from backend.tools.base_tool import BaseTool, ToolDefinition, ToolParameter, ToolExecutionError
from backend.tools.tool_config import get_tool_config
import re


class CalculatorTool(BaseTool):
    def __init__(self):
        super().__init__()
        config = get_tool_config()
        self.max_expression_length = config.get('calculator', 'max_expression_length', 1000)
        self._definition.timeout = config.get('calculator', 'timeout', self._definition.timeout)
        for parameter in self._definition.parameters:
            if parameter.name == "expression":
                parameter.max_length = self.max_expression_length
                break

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="calculator",
            description="执行数学计算，支持基本运算（+、-、*、/、**）、括号和常用数学函数（sqrt、sin、cos、tan、log等）",
            category="calculation",
            strict_validation=True,
            parameters=[
                ToolParameter(
                    name="expression",
                    type="string",
                    description="要计算的数学表达式，例如：'2 + 3 * 4'、'sqrt(16)'、'sin(3.14/2)'",
                    required=True,
                    min_length=1,
                    max_length=1000,
                )
            ]
        )

    async def execute(self, expression: str, **kwargs) -> Dict[str, Any]:
        try:
            self.logger.info(f"开始计算表达式: {expression}")

            # 清理表达式
            expression = expression.strip()

            if len(expression) > self.max_expression_length:
                return {
                    "success": False,
                    "data": None,
                    "error": f"表达式长度不能超过 {self.max_expression_length} 个字符",
                    "error_code": "TOOL_INVALID_PARAMETER",
                    "error_type": "parameter_error",
                }

            # 安全检查：只允许数字、运算符和数学函数
            if not self._is_safe_expression(expression):
                self.logger.warning(f"表达式包含不安全字符: {expression}")
                return {
                    "success": False,
                    "data": None,
                    "error": "表达式包含不安全的字符或函数",
                    "error_code": "TOOL_INVALID_PARAMETER",
                    "error_type": "parameter_error",
                }

            # 替换数学函数为Python函数
            safe_expression = self._prepare_expression(expression)
            self.logger.debug(f"处理后的表达式: {safe_expression}")

            # 定义安全的数学函数
            import math
            safe_dict = {
                "sqrt": math.sqrt,
                "sin": math.sin,
                "cos": math.cos,
                "tan": math.tan,
                "log": math.log,
                "log10": math.log10,
                "exp": math.exp,
                "abs": abs,
                "pow": pow,
                "pi": math.pi,
                "e": math.e,
                "__builtins__": {}  # 禁用内置函数
            }

            # 执行计算
            result = eval(safe_expression, safe_dict, {})

            # 格式化结果
            if isinstance(result, float):
                # 如果是整数，显示为整数
                if result.is_integer():
                    result = int(result)
                else:
                    # 保留6位小数
                    result = round(result, 6)

            self.logger.info(f"计算完成: {expression} = {result}")
            return {
                "success": True,
                "data": {
                    "expression": expression,
                    "result": result,
                    "result_str": str(result)
                },
                "error": None
            }

        except ZeroDivisionError:
            self.logger.error(f"计算错误: 除数不能为零 - {expression}")
            return {
                "success": False,
                "data": None,
                "error": "除数不能为零",
                "error_code": "TOOL_EXECUTION_ERROR",
                "error_type": "execution_error",
            }
        except ValueError as e:
            self.logger.error(f"数值错误: {str(e)} - {expression}")
            return {
                "success": False,
                "data": None,
                "error": f"数值错误: {str(e)}",
                "error_code": "TOOL_EXECUTION_ERROR",
                "error_type": "execution_error",
            }
        except SyntaxError:
            self.logger.error(f"语法错误: {expression}")
            return {
                "success": False,
                "data": None,
                "error": "表达式语法错误",
                "error_code": "TOOL_INVALID_PARAMETER",
                "error_type": "parameter_error",
            }
        except Exception as e:
            self.logger.error(f"计算失败: {str(e)} - {expression}", exc_info=True)
            raise ToolExecutionError(f"计算失败: {str(e)}") from e

    def _is_safe_expression(self, expression: str) -> bool:
        # 允许的字符：数字、运算符、括号、小数点、空格、数学函数名
        allowed_pattern = r'^[0-9+\-*/().\s,a-z_]+$'

        if not re.match(allowed_pattern, expression.lower()):
            return False

        # 禁止的关键字
        forbidden_keywords = [
            "import", "exec", "eval", "compile", "open", "file",
            "__", "lambda", "class", "def", "return", "yield",
            "global", "nonlocal", "del", "raise", "assert"
        ]

        expression_lower = expression.lower()
        for keyword in forbidden_keywords:
            if keyword in expression_lower:
                return False

        return True

    def _prepare_expression(self, expression: str) -> str:
        # 替换常见的数学符号
        expression = expression.replace("^", "**")  # 幂运算
        expression = expression.replace("×", "*")   # 乘法
        expression = expression.replace("÷", "/")   # 除法

        return expression
