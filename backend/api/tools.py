
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, ConfigDict, Field
from typing import Dict, Any, List, Optional
import time
import json
import uuid
from backend.tools.tool_registry import get_all_tools, get_tool
from backend.api.dependencies import get_current_user
from backend.models.user import User
from backend.utils.logger import get_logger
from backend.database.database_manager import get_database_manager

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tools",
    tags=["工具管理"]
)


# ==================== 请求模型 ====================

class ToolExecuteRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "parameters": {
                    "text": "Hello, world!",
                    "source_lang": "en",
                    "target_lang": "zh"
                }
            }
        }
    )

    parameters: Dict[str, Any] = Field(..., description="工具参数")


# ==================== 响应模型 ====================

class ToolInfo(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "translation",
                "description": "多语言翻译工具",
                "category": "language",
                "parameters": [
                    {
                        "name": "text",
                        "type": "string",
                        "description": "要翻译的文本",
                        "required": True
                    }
                ],
                "timeout": 30
            }
        }
    )

    name: str = Field(..., description="工具名称")
    description: str = Field(..., description="工具描述")
    category: str = Field(..., description="工具分类")
    parameters: List[Dict[str, Any]] = Field(..., description="参数列表")
    timeout: int = Field(..., description="超时时间（秒）")


class ToolListResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "data": [],
                "total": 9
            }
        }
    )

    success: bool = Field(True, description="是否成功")
    data: List[ToolInfo] = Field(..., description="工具列表")
    total: int = Field(..., description="工具总数")


class ToolDetailResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "data": {
                    "name": "translation",
                    "description": "多语言翻译工具",
                    "category": "language",
                    "parameters": [],
                    "timeout": 30
                }
            }
        }
    )

    success: bool = Field(True, description="是否成功")
    data: ToolInfo = Field(..., description="工具详情")


class ToolExecuteResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "data": {
                    "translated_text": "你好，世界！"
                },
                "error": None,
                "error_code": None,
                "error_type": None,
                "metadata": {
                    "tool_name": "translation"
                }
            }
        }
    )

    success: bool = Field(..., description="是否成功")
    data: Optional[Dict[str, Any]] = Field(None, description="执行结果")
    error: Optional[str] = Field(None, description="错误信息")
    error_code: Optional[str] = Field(None, description="稳定错误码")
    error_type: Optional[str] = Field(None, description="错误分类")
    metadata: Optional[Dict[str, Any]] = Field(None, description="附加元数据")


# ==================== API端点 ====================

@router.get(
    "/categories/list",
    summary="获取工具分类列表",
    description="获取所有工具的分类列表"
)
async def get_tool_categories(
    current_user: User = Depends(get_current_user)
):
    try:
        logger.info(f"用户 {current_user.user_id} 请求工具分类列表")

        all_tools = get_all_tools()

        categories = {}
        for _, tool_instance in all_tools.items():
            definition = tool_instance.get_definition()
            category = definition.category

            if category not in categories:
                categories[category] = {
                    "category": category,
                    "count": 0,
                    "tools": []
                }

            categories[category]["count"] += 1
            categories[category]["tools"].append(definition.name)

        logger.info(f"返回 {len(categories)} 个分类")

        return {
            "success": True,
            "data": list(categories.values()),
            "total": len(categories)
        }

    except Exception as e:
        logger.error(f"获取工具分类失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取工具分类失败: {str(e)}")


@router.get(
    "",
    response_model=ToolListResponse,
    summary="获取所有工具列表",
    description="获取系统中所有可用工具的列表"
)
async def get_tools_list(
    category: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    try:
        logger.info(f"用户 {current_user.user_id} 请求工具列表，分类: {category}")

        # 获取所有工具
        all_tools = get_all_tools()

        # 转换为工具信息列表
        tools_info = []
        for tool_name, tool_instance in all_tools.items():
            definition = tool_instance.get_definition()

            # 如果指定了分类，只返回该分类的工具
            if category and definition.category != category:
                continue

            # 转换参数列表
            parameters = [
                {
                    "name": param.name,
                    "type": param.type,
                    "description": param.description,
                    "required": param.required,
                    "default": param.default,
                    "enum": param.enum
                }
                for param in definition.parameters
            ]

            tools_info.append(ToolInfo(
                name=definition.name,
                description=definition.description,
                category=definition.category,
                parameters=parameters,
                timeout=definition.timeout
            ))

        logger.info(f"返回 {len(tools_info)} 个工具")

        return ToolListResponse(
            success=True,
            data=tools_info,
            total=len(tools_info)
        )

    except Exception as e:
        logger.error(f"获取工具列表失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取工具列表失败: {str(e)}")


@router.get(
    "/{tool_name}",
    response_model=ToolDetailResponse,
    summary="获取工具详情",
    description="获取指定工具的详细信息"
)
async def get_tool_detail(
    tool_name: str,
    current_user: User = Depends(get_current_user)
):
    try:
        logger.info(f"用户 {current_user.user_id} 请求工具详情: {tool_name}")

        # 获取工具实例
        tool_instance = get_tool(tool_name)
        if not tool_instance:
            raise HTTPException(status_code=404, detail=f"工具不存在: {tool_name}")

        # 获取工具定义
        definition = tool_instance.get_definition()

        # 转换参数列表
        parameters = [
            {
                "name": param.name,
                "type": param.type,
                "description": param.description,
                "required": param.required,
                "default": param.default,
                "enum": param.enum
            }
            for param in definition.parameters
        ]

        tool_info = ToolInfo(
            name=definition.name,
            description=definition.description,
            category=definition.category,
            parameters=parameters,
            timeout=definition.timeout
        )

        logger.info(f"返回工具详情: {tool_name}")

        return ToolDetailResponse(
            success=True,
            data=tool_info
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取工具详情失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取工具详情失败: {str(e)}")


@router.post(
    "/{tool_name}/execute",
    response_model=ToolExecuteResponse,
    summary="执行工具",
    description="执行指定的工具"
)
async def execute_tool(
    tool_name: str,
    request: ToolExecuteRequest,
    current_user: User = Depends(get_current_user)
):
    start_time = time.time()
    db_manager = get_database_manager()
    execution_id = None

    try:
        logger.info(f"用户 {current_user.user_id} 执行工具: {tool_name}, 参数: {request.parameters}")

        # 获取工具实例
        tool_instance = get_tool(tool_name)
        if not tool_instance:
            raise HTTPException(status_code=404, detail=f"工具不存在: {tool_name}")

        # 创建智能体执行记录
        try:
            # 生成execution_id
            execution_id = str(uuid.uuid4())

            # 注意：工具直接调用没有会话上下文，conversation_id 设为 NULL
            db_manager.execute_update(
                """
                INSERT INTO agent_executions
                (execution_id, conversation_id, agent_name, agent_type, input_data, status)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    execution_id,
                    None,  # 直接工具调用，无会话上下文
                    tool_name,
                    'tool',
                    json.dumps({"tool": tool_name, "params": request.parameters, "user_id": current_user.user_id}, ensure_ascii=False),
                    'running'
                )
            )
            logger.info(f"创建智能体执行记录，ID: {execution_id}")
        except Exception as db_error:
            logger.error(f"创建智能体执行记录失败: {str(db_error)}", exc_info=True)

        # 执行工具
        result = await tool_instance.safe_execute(**request.parameters)

        # 计算执行时间
        execution_time = int((time.time() - start_time) * 1000)

        logger.info(f"工具执行完成: {tool_name}, 成功: {result.get('success')}, 执行时间: {execution_time}ms")

        # 保存工具调用记录
        if execution_id:
            try:
                # 生成call_id
                call_id = str(uuid.uuid4())

                db_manager.execute_update(
                    """
                    INSERT INTO tool_calls
                    (call_id, execution_id, tool_name, tool_input, tool_output, status, error_message, execution_time_ms)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        call_id,
                        execution_id,
                        tool_name,
                        json.dumps(request.parameters, ensure_ascii=False),
                        json.dumps(result.get('data'), ensure_ascii=False) if result.get('success') else None,
                        'success' if result.get('success') else 'failed',
                        result.get('error'),
                        execution_time
                    )
                )

                # 更新智能体执行记录状态
                db_manager.execute_update(
                    """
                    UPDATE agent_executions
                    SET status = %s, output_data = %s, execution_time_ms = %s
                    WHERE execution_id = %s
                    """,
                    (
                        'success' if result.get('success') else 'failed',
                        json.dumps(result, ensure_ascii=False),
                        execution_time,
                        execution_id
                    )
                )

                logger.info(f"工具调用记录已保存到数据库，execution_id: {execution_id}")
            except Exception as db_error:
                logger.error(f"保存工具调用记录失败: {str(db_error)}", exc_info=True)

        return ToolExecuteResponse(
            success=result.get("success", False),
            data=result.get("data"),
            error=result.get("error"),
            error_code=result.get("error_code"),
            error_type=result.get("error_type"),
            metadata=result.get("metadata"),
        )

    except HTTPException:
        raise
    except Exception as e:
        execution_time = int((time.time() - start_time) * 1000)
        logger.error(f"执行工具失败: {str(e)}", exc_info=True)

        # 记录失败的调用
        if execution_id:
            try:
                call_id = str(uuid.uuid4())

                db_manager.execute_update(
                    """
                    INSERT INTO tool_calls
                    (call_id, execution_id, tool_name, tool_input, status, error_message, execution_time_ms)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        call_id,
                        execution_id,
                        tool_name,
                        json.dumps(request.parameters, ensure_ascii=False),
                        'failed',
                        str(e),
                        execution_time
                    )
                )

                # 更新智能体执行记录状态
                db_manager.execute_update(
                    """
                    UPDATE agent_executions
                    SET status = 'failed', execution_time_ms = %s
                    WHERE execution_id = %s
                    """,
                    (execution_time, execution_id)
                )

                logger.info(f"工具调用失败记录已保存到数据库，execution_id: {execution_id}")
            except Exception as db_error:
                logger.error(f"保存失败记录失败: {str(db_error)}", exc_info=True)

        return ToolExecuteResponse(
            success=False,
            data=None,
            error=f"执行工具失败: {str(e)}",
            error_code="TOOL_EXECUTION_ERROR",
            error_type="execution_error",
            metadata={"tool_name": tool_name},
        )
