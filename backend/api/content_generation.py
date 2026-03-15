"""
内容生成API
提供小说生成、脚本生成、内容优化等接口
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import time
import json
import uuid
from backend.tools.tool_registry import get_tool
from backend.api.dependencies import get_current_user
from backend.contracts.sse import build_sse_event
from backend.models.user import User
from backend.utils.logger import get_logger
from backend.database.database_manager import get_database_manager

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/content",
    tags=["内容生成"]
)


# ==================== 辅助函数 ====================

def resolve_current_user_id(current_user: User | Dict[str, Any]) -> str:
    """Resolve the authenticated user id from dependency output."""
    user_id = current_user.get("user_id") if isinstance(current_user, dict) else getattr(current_user, "user_id", None)

    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")

    return user_id


def _request_id(request: Request) -> str | None:
    return getattr(getattr(request, "state", None), "request_id", None)


def _with_generation_id(data: Optional[Dict[str, Any]], generation_id: str) -> Dict[str, Any]:
    payload = dict(data or {})
    payload["generation_id"] = generation_id
    return payload


def _extract_result_preview(data: Optional[Dict[str, Any]]) -> str:
    if not data:
        return ""

    for key in ("content", "optimized_content", "check_result", "continued_content"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value

    for key in ("outline", "character", "worldview", "storyboard"):
        value = data.get(key)
        if isinstance(value, dict):
            for nested_key in ("raw_outline", "raw_character", "raw_worldview", "raw_storyboard"):
                nested_value = value.get(nested_key)
                if isinstance(nested_value, str) and nested_value:
                    return nested_value

    return json.dumps(data, ensure_ascii=False, indent=2)


def _execute_db_write(query: str, params: tuple[Any, ...]) -> None:
    """Execute a write statement across supported DB manager interfaces."""
    db_manager = get_database_manager()

    if hasattr(db_manager, "execute_update"):
        db_manager.execute_update(query, params)
        return

    execute_query = getattr(db_manager, "execute_query", None)
    if not callable(execute_query):
        raise AttributeError("Database manager does not support write execution")

    try:
        execute_query(query, params, fetch_one=False, fetch_all=False)
    except TypeError:
        try:
            execute_query(query, params, fetch=False)
        except TypeError:
            execute_query(query, params)


def _format_content_sse_data(
    event_type: str,
    content: Any = None,
    *,
    request_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    message: Optional[str] = None,
) -> str:
    event = build_sse_event(
        event_type,
        content,
        message=message,
        metadata=metadata or {},
        request_id=request_id,
    )
    return f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _stream_content_generation(
    *,
    request_id: Optional[str],
    user_id: str,
    content_type: str,
    action: str,
    input_params: Dict[str, Any],
    tool_name: str,
    tool_params: Dict[str, Any],
):
    generation_id, start_time = await save_content_generation(
        user_id=user_id,
        content_type=content_type,
        action=action,
        input_params=input_params,
        tool_name=tool_name,
    )

    stream_metadata = {
        "generation_id": generation_id,
        "content_type": content_type,
        "action": action,
        "tool_name": tool_name,
    }

    try:
        tool = get_tool(tool_name)
        if not tool:
            error_message = f"工具不可用: {tool_name}"
            await update_content_generation(generation_id, start_time, {"success": False, "data": None, "error": error_message})
            yield _format_content_sse_data("error", None, request_id=request_id, metadata=stream_metadata, message=error_message)
            return

        yield _format_content_sse_data(
            "thinking",
            None,
            request_id=request_id,
            metadata=stream_metadata,
            message="stream_started",
        )

        final_result: Optional[Dict[str, Any]] = None

        if hasattr(tool, "execute_stream"):
            async for event in tool.execute_stream(action=action, **tool_params):
                event_type = event.get("type")
                if event_type == "content":
                    chunk = event.get("content") or ""
                    if chunk:
                        yield _format_content_sse_data("content", chunk, request_id=request_id, metadata=stream_metadata)
                elif event_type == "result":
                    final_result = {
                        "success": True,
                        "data": _with_generation_id(event.get("data"), generation_id),
                        "error": None,
                    }
                    yield _format_content_sse_data("result", final_result["data"], request_id=request_id, metadata=stream_metadata)
                elif event_type == "error":
                    error_message = str(event.get("error") or "流式生成失败")
                    final_result = {"success": False, "data": None, "error": error_message}
                    break
        else:
            fallback_result = await tool.safe_execute(action=action, **tool_params)
            final_result = {
                "success": bool(fallback_result.get("success")),
                "data": _with_generation_id(fallback_result.get("data"), generation_id) if fallback_result.get("success") else None,
                "error": fallback_result.get("error"),
            }

            preview = _extract_result_preview(final_result.get("data")) if final_result.get("success") else ""
            if preview:
                yield _format_content_sse_data("content", preview, request_id=request_id, metadata=stream_metadata)
            if final_result.get("success"):
                yield _format_content_sse_data("result", final_result["data"], request_id=request_id, metadata=stream_metadata)

        if not final_result:
            final_result = {"success": False, "data": None, "error": "流式生成未返回结果"}

        await update_content_generation(generation_id, start_time, final_result)

        if final_result.get("success"):
            yield _format_content_sse_data("done", final_result.get("data"), request_id=request_id, metadata=stream_metadata)
            return

        yield _format_content_sse_data(
            "error",
            None,
            request_id=request_id,
            metadata=stream_metadata,
            message=str(final_result.get("error") or "流式生成失败"),
        )
    except Exception as error:
        error_message = str(error)
        logger.error("内容生成流式处理失败: %s", error_message, exc_info=True)
        await update_content_generation(generation_id, start_time, {"success": False, "data": None, "error": error_message})
        yield _format_content_sse_data("error", None, request_id=request_id, metadata=stream_metadata, message=error_message)


async def save_content_generation(
    user_id: str,
    content_type: str,
    action: str,
    input_params: dict,
    tool_name: str,
    conversation_id: Optional[str] = None
) -> tuple[str, int]:
    """
    保存内容生成记录到数据库（pending状态）

    Args:
        user_id: 用户ID
        content_type: 内容类型（novel/script/optimization）
        action: 操作类型（outline/chapter/scene等）
        input_params: 输入参数
        tool_name: 工具名称
        conversation_id: 会话ID（可选）

    Returns:
        (generation_id, start_time_ms): 生成记录ID和开始时间戳
    """
    generation_id = str(uuid.uuid4())
    start_time = int(time.time() * 1000)

    try:
        _execute_db_write(
            """
            INSERT INTO content_generations
            (id, user_id, conversation_id, content_type, action, input_params, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                generation_id,
                user_id,
                conversation_id,
                content_type,
                action,
                json.dumps(input_params, ensure_ascii=False),
                'pending'
            )
        )
        logger.info(f"创建内容生成记录，ID: {generation_id}, 类型: {content_type}, 操作: {action}")
    except Exception as e:
        logger.error(f"创建内容生成记录失败: {str(e)}", exc_info=True)

    return generation_id, start_time


async def update_content_generation(
    generation_id: str,
    start_time_ms: int,
    result: dict
):
    """
    更新内容生成记录（completed或failed状态）

    Args:
        generation_id: 生成记录ID
        start_time_ms: 开始时间戳（毫秒）
        result: 执行结果
    """
    execution_time = int(time.time() * 1000) - start_time_ms

    try:
        if result.get('success'):
            _execute_db_write(
                """
                UPDATE content_generations
                SET output_content = %s,
                    status = %s,
                    execution_time = %s
                WHERE id = %s
                """,
                (
                    json.dumps(result.get('data'), ensure_ascii=False),
                    'completed',
                    execution_time,
                    generation_id
                )
            )
            logger.info(f"内容生成完成，ID: {generation_id}, 执行时间: {execution_time}ms")
        else:
            _execute_db_write(
                """
                UPDATE content_generations
                SET status = %s,
                    error_message = %s,
                    execution_time = %s
                WHERE id = %s
                """,
                (
                    'failed',
                    result.get('error'),
                    execution_time,
                    generation_id
                )
            )
            logger.info(f"内容生成失败，ID: {generation_id}, 错误: {result.get('error')}")
    except Exception as e:
        logger.error(f"更新内容生成记录失败: {str(e)}", exc_info=True)


# ==================== 请求模型 ====================

class NovelOutlineRequest(BaseModel):
    """小说大纲生成请求"""
    title: Optional[str] = Field(None, description="小说标题")
    theme: Optional[str] = Field(None, description="小说主题")
    genre: Optional[str] = Field(None, description="小说类型")
    style: Optional[str] = Field(None, description="写作风格")


class NovelChapterRequest(BaseModel):
    """小说章节生成请求"""
    chapter_number: int = Field(..., description="章节编号")
    chapter_title: Optional[str] = Field(None, description="章节标题")
    outline: Optional[str] = Field(None, description="小说大纲")
    genre: Optional[str] = Field(None, description="小说类型")
    style: Optional[str] = Field(None, description="写作风格")
    word_count: int = Field(2000, description="目标字数")


class NovelCharacterRequest(BaseModel):
    """角色设定生成请求"""
    character_name: Optional[str] = Field(None, description="角色名称")
    genre: Optional[str] = Field(None, description="小说类型")
    theme: Optional[str] = Field(None, description="故事主题")


class NovelWorldviewRequest(BaseModel):
    """世界观设定生成请求"""
    title: Optional[str] = Field(None, description="小说标题")
    theme: Optional[str] = Field(None, description="故事主题")
    genre: Optional[str] = Field(None, description="小说类型")


class NovelContinueRequest(BaseModel):
    """小说续写请求"""
    previous_content: str = Field(..., description="前文内容")
    genre: Optional[str] = Field(None, description="小说类型")
    style: Optional[str] = Field(None, description="写作风格")
    word_count: int = Field(1000, description="目标字数")


class ScriptOutlineRequest(BaseModel):
    """脚本大纲生成请求"""
    script_type: str = Field(..., description="脚本类型")
    title: Optional[str] = Field(None, description="脚本标题")
    theme: Optional[str] = Field(None, description="脚本主题")
    style: Optional[str] = Field(None, description="脚本风格")
    duration: Optional[int] = Field(None, description="时长（分钟）")
    target_audience: Optional[str] = Field(None, description="目标受众")


class ScriptSceneRequest(BaseModel):
    """场景脚本生成请求"""
    script_type: str = Field(..., description="脚本类型")
    scene_number: int = Field(1, description="场景编号")
    scene_description: Optional[str] = Field(None, description="场景描述")
    characters: Optional[str] = Field(None, description="角色列表")
    style: Optional[str] = Field(None, description="脚本风格")
    outline: Optional[str] = Field(None, description="脚本大纲")


class ScriptDialogueRequest(BaseModel):
    """对白生成请求"""
    script_type: str = Field(..., description="脚本类型")
    characters: Optional[str] = Field(None, description="角色列表")
    scene_description: Optional[str] = Field(None, description="场景描述")
    style: Optional[str] = Field(None, description="脚本风格")


class ScriptStoryboardRequest(BaseModel):
    """分镜脚本生成请求"""
    script_type: str = Field(..., description="脚本类型")
    scene_description: Optional[str] = Field(None, description="场景描述")
    style: Optional[str] = Field(None, description="脚本风格")


class ScriptCompleteRequest(BaseModel):
    """完整脚本生成请求"""
    script_type: str = Field(..., description="脚本类型")
    title: Optional[str] = Field(None, description="脚本标题")
    theme: Optional[str] = Field(None, description="脚本主题")
    style: Optional[str] = Field(None, description="脚本风格")
    duration: Optional[int] = Field(None, description="时长（分钟）")
    target_audience: Optional[str] = Field(None, description="目标受众")


class ContentOptimizeRequest(BaseModel):
    """内容优化请求"""
    action: str = Field(..., description="操作类型")
    content: str = Field(..., description="要优化的内容")
    target_style: Optional[str] = Field(None, description="目标风格")
    target_length: Optional[int] = Field(None, description="目标字数")
    keywords: Optional[str] = Field(None, description="关键词")
    requirements: Optional[str] = Field(None, description="特殊要求")


# ==================== 响应模型 ====================

class ContentGenerationResponse(BaseModel):
    """内容生成响应"""
    success: bool = Field(..., description="是否成功")
    data: Optional[Dict[str, Any]] = Field(None, description="生成结果")
    error: Optional[str] = Field(None, description="错误信息")


# ==================== 小说生成API ====================

@router.post(
    "/novel/outline",
    response_model=ContentGenerationResponse,
    summary="生成小说大纲",
    description="根据标题和主题生成小说大纲"
)
async def generate_novel_outline(
    http_request: Request,
    request: NovelOutlineRequest,
    stream: bool = False,
    current_user: User | Dict[str, Any] = Depends(get_current_user)
):
    """生成小说大纲"""
    generation_id = None
    start_time = None

    try:
        current_user_id = resolve_current_user_id(current_user)
        if stream:
            return StreamingResponse(
                _stream_content_generation(
                    request_id=_request_id(http_request),
                    user_id=current_user_id,
                    content_type='novel',
                    action='outline',
                    input_params=request.model_dump(),
                    tool_name='novel_generator',
                    tool_params={
                        'title': request.title,
                        'theme': request.theme,
                        'genre': request.genre,
                        'style': request.style,
                    },
                ),
                media_type="text/event-stream",
            )
        logger.info(f"用户 {current_user_id} 请求生成小说大纲: {request.title}")

        # 保存生成记录（pending状态）
        generation_id, start_time = await save_content_generation(
            user_id=current_user_id,
            content_type='novel',
            action='outline',
            input_params=request.model_dump(),
            tool_name='novel_generator'
        )

        tool = get_tool("novel_generator")
        if not tool:
            raise HTTPException(status_code=500, detail="小说生成工具不可用")

        result = await tool.safe_execute(
            action="outline",
            title=request.title,
            theme=request.theme,
            genre=request.genre,
            style=request.style
        )

        # 更新生成记录（completed或failed状态）
        if generation_id:
            await update_content_generation(generation_id, start_time, result)

        # 在返回结果中包含generation_id
        if result.get('success') and result.get('data'):
            result['data']['generation_id'] = generation_id

        logger.info(f"小说大纲生成完成，成功: {result.get('success')}")
        return ContentGenerationResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成小说大纲失败: {str(e)}", exc_info=True)
        error_result = {"success": False, "data": None, "error": str(e)}

        # 更新失败记录
        if generation_id and start_time:
            await update_content_generation(generation_id, start_time, error_result)

        return ContentGenerationResponse(**error_result)


@router.post(
    "/novel/chapter",
    response_model=ContentGenerationResponse,
    summary="生成小说章节",
    description="生成指定章节的小说内容"
)
async def generate_novel_chapter(
    http_request: Request,
    request: NovelChapterRequest,
    stream: bool = False,
    current_user: User | Dict[str, Any] = Depends(get_current_user)
):
    """生成小说章节"""
    generation_id = None
    start_time = None

    try:
        current_user_id = resolve_current_user_id(current_user)
        if stream:
            return StreamingResponse(
                _stream_content_generation(
                    request_id=_request_id(http_request),
                    user_id=current_user_id,
                    content_type='novel',
                    action='chapter',
                    input_params=request.model_dump(),
                    tool_name='novel_generator',
                    tool_params={
                        'chapter_number': request.chapter_number,
                        'chapter_title': request.chapter_title,
                        'outline': request.outline,
                        'genre': request.genre,
                        'style': request.style,
                        'word_count': request.word_count,
                    },
                ),
                media_type="text/event-stream",
            )
        logger.info(f"用户 {current_user_id} 请求生成第{request.chapter_number}章")

        # 保存生成记录
        generation_id, start_time = await save_content_generation(
            user_id=current_user_id,
            content_type='novel',
            action='chapter',
            input_params=request.model_dump(),
            tool_name='novel_generator'
        )

        tool = get_tool("novel_generator")
        if not tool:
            raise HTTPException(status_code=500, detail="小说生成工具不可用")

        result = await tool.safe_execute(
            action="chapter",
            chapter_number=request.chapter_number,
            chapter_title=request.chapter_title,
            outline=request.outline,
            genre=request.genre,
            style=request.style,
            word_count=request.word_count
        )

        # 更新生成记录
        if generation_id:
            await update_content_generation(generation_id, start_time, result)

        if result.get('success') and result.get('data'):
            result['data']['generation_id'] = generation_id

        logger.info(f"小说章节生成完成，成功: {result.get('success')}")
        return ContentGenerationResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成小说章节失败: {str(e)}", exc_info=True)
        error_result = {"success": False, "data": None, "error": str(e)}

        if generation_id and start_time:
            await update_content_generation(generation_id, start_time, error_result)

        return ContentGenerationResponse(**error_result)


@router.post(
    "/novel/character",
    response_model=ContentGenerationResponse,
    summary="生成角色设定",
    description="生成小说角色的详细设定"
)
async def generate_novel_character(
    http_request: Request,
    request: NovelCharacterRequest,
    stream: bool = False,
    current_user: User | Dict[str, Any] = Depends(get_current_user)
):
    """生成角色设定"""
    generation_id = None
    start_time = None

    try:
        current_user_id = resolve_current_user_id(current_user)
        if stream:
            return StreamingResponse(
                _stream_content_generation(
                    request_id=_request_id(http_request),
                    user_id=current_user_id,
                    content_type='novel',
                    action='character',
                    input_params=request.model_dump(),
                    tool_name='novel_generator',
                    tool_params={
                        'character_name': request.character_name,
                        'genre': request.genre,
                        'theme': request.theme,
                    },
                ),
                media_type="text/event-stream",
            )
        logger.info(f"用户 {current_user_id} 请求生成角色设定: {request.character_name}")

        generation_id, start_time = await save_content_generation(
            user_id=current_user_id,
            content_type='novel',
            action='character',
            input_params=request.model_dump(),
            tool_name='novel_generator'
        )

        tool = get_tool("novel_generator")
        if not tool:
            raise HTTPException(status_code=500, detail="小说生成工具不可用")

        result = await tool.safe_execute(
            action="character",
            character_name=request.character_name,
            genre=request.genre,
            theme=request.theme
        )

        if generation_id:
            await update_content_generation(generation_id, start_time, result)

        if result.get('success') and result.get('data'):
            result['data']['generation_id'] = generation_id

        logger.info(f"角色设定生成完成，成功: {result.get('success')}")
        return ContentGenerationResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成角色设定失败: {str(e)}", exc_info=True)
        error_result = {"success": False, "data": None, "error": str(e)}

        if generation_id and start_time:
            await update_content_generation(generation_id, start_time, error_result)

        return ContentGenerationResponse(**error_result)


@router.post(
    "/novel/worldview",
    response_model=ContentGenerationResponse,
    summary="生成世界观设定",
    description="生成小说的世界观设定"
)
async def generate_novel_worldview(
    http_request: Request,
    request: NovelWorldviewRequest,
    stream: bool = False,
    current_user: User | Dict[str, Any] = Depends(get_current_user)
):
    """生成世界观设定"""
    generation_id = None
    start_time = None

    try:
        current_user_id = resolve_current_user_id(current_user)
        if stream:
            return StreamingResponse(
                _stream_content_generation(
                    request_id=_request_id(http_request),
                    user_id=current_user_id,
                    content_type='novel',
                    action='worldview',
                    input_params=request.model_dump(),
                    tool_name='novel_generator',
                    tool_params={
                        'title': request.title,
                        'theme': request.theme,
                        'genre': request.genre,
                    },
                ),
                media_type="text/event-stream",
            )
        logger.info(f"用户 {current_user_id} 请求生成世界观设定")

        generation_id, start_time = await save_content_generation(
            user_id=current_user_id,
            content_type='novel',
            action='worldview',
            input_params=request.model_dump(),
            tool_name='novel_generator'
        )

        tool = get_tool("novel_generator")
        if not tool:
            raise HTTPException(status_code=500, detail="小说生成工具不可用")

        result = await tool.safe_execute(
            action="worldview",
            title=request.title,
            theme=request.theme,
            genre=request.genre
        )

        if generation_id:
            await update_content_generation(generation_id, start_time, result)

        if result.get('success') and result.get('data'):
            result['data']['generation_id'] = generation_id

        logger.info(f"世界观设定生成完成，成功: {result.get('success')}")
        return ContentGenerationResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成世界观设定失败: {str(e)}", exc_info=True)
        error_result = {"success": False, "data": None, "error": str(e)}

        if generation_id and start_time:
            await update_content_generation(generation_id, start_time, error_result)

        return ContentGenerationResponse(**error_result)


@router.post(
    "/novel/continue",
    response_model=ContentGenerationResponse,
    summary="续写小说",
    description="根据前文内容续写小说"
)
async def continue_novel(
    http_request: Request,
    request: NovelContinueRequest,
    stream: bool = False,
    current_user: User | Dict[str, Any] = Depends(get_current_user)
):
    """续写小说"""
    generation_id = None
    start_time = None

    try:
        current_user_id = resolve_current_user_id(current_user)
        if stream:
            return StreamingResponse(
                _stream_content_generation(
                    request_id=_request_id(http_request),
                    user_id=current_user_id,
                    content_type='novel',
                    action='continue',
                    input_params=request.model_dump(),
                    tool_name='novel_generator',
                    tool_params={
                        'previous_content': request.previous_content,
                        'genre': request.genre,
                        'style': request.style,
                        'word_count': request.word_count,
                    },
                ),
                media_type="text/event-stream",
            )
        logger.info(f"用户 {current_user_id} 请求续写小说")

        generation_id, start_time = await save_content_generation(
            user_id=current_user_id,
            content_type='novel',
            action='continue',
            input_params=request.model_dump(),
            tool_name='novel_generator'
        )

        tool = get_tool("novel_generator")
        if not tool:
            raise HTTPException(status_code=500, detail="小说生成工具不可用")

        result = await tool.safe_execute(
            action="continue",
            previous_content=request.previous_content,
            genre=request.genre,
            style=request.style,
            word_count=request.word_count
        )

        if generation_id:
            await update_content_generation(generation_id, start_time, result)

        if result.get('success') and result.get('data'):
            result['data']['generation_id'] = generation_id

        logger.info(f"小说续写完成，成功: {result.get('success')}")
        return ContentGenerationResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"续写小说失败: {str(e)}", exc_info=True)
        error_result = {"success": False, "data": None, "error": str(e)}

        if generation_id and start_time:
            await update_content_generation(generation_id, start_time, error_result)

        return ContentGenerationResponse(**error_result)


# ==================== 脚本生成API ====================

@router.post(
    "/script/outline",
    response_model=ContentGenerationResponse,
    summary="生成脚本大纲",
    description="生成脚本的详细大纲"
)
async def generate_script_outline(
    http_request: Request,
    request: ScriptOutlineRequest,
    stream: bool = False,
    current_user: User | Dict[str, Any] = Depends(get_current_user)
):
    """生成脚本大纲"""
    generation_id = None
    start_time = None

    try:
        current_user_id = resolve_current_user_id(current_user)
        if stream:
            return StreamingResponse(
                _stream_content_generation(
                    request_id=_request_id(http_request),
                    user_id=current_user_id,
                    content_type='script',
                    action='outline',
                    input_params=request.model_dump(),
                    tool_name='script_generator',
                    tool_params={
                        'script_type': request.script_type,
                        'title': request.title,
                        'theme': request.theme,
                        'style': request.style,
                        'duration': request.duration,
                        'target_audience': request.target_audience,
                    },
                ),
                media_type="text/event-stream",
            )
        logger.info(f"用户 {current_user_id} 请求生成脚本大纲: {request.title}")

        generation_id, start_time = await save_content_generation(
            user_id=current_user_id,
            content_type='script',
            action='outline',
            input_params=request.model_dump(),
            tool_name='script_generator'
        )

        tool = get_tool("script_generator")
        if not tool:
            raise HTTPException(status_code=500, detail="脚本生成工具不可用")

        result = await tool.safe_execute(
            action="outline",
            script_type=request.script_type,
            title=request.title,
            theme=request.theme,
            style=request.style,
            duration=request.duration,
            target_audience=request.target_audience
        )

        if generation_id:
            await update_content_generation(generation_id, start_time, result)

        if result.get('success') and result.get('data'):
            result['data']['generation_id'] = generation_id

        logger.info(f"脚本大纲生成完成，成功: {result.get('success')}")
        return ContentGenerationResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成脚本大纲失败: {str(e)}", exc_info=True)
        error_result = {"success": False, "data": None, "error": str(e)}

        if generation_id and start_time:
            await update_content_generation(generation_id, start_time, error_result)

        return ContentGenerationResponse(**error_result)


@router.post(
    "/script/scene",
    response_model=ContentGenerationResponse,
    summary="生成场景脚本",
    description="生成指定场景的脚本内容"
)
async def generate_script_scene(
    http_request: Request,
    request: ScriptSceneRequest,
    stream: bool = False,
    current_user: User | Dict[str, Any] = Depends(get_current_user)
):
    """生成场景脚本"""
    generation_id = None
    start_time = None

    try:
        current_user_id = resolve_current_user_id(current_user)
        if stream:
            return StreamingResponse(
                _stream_content_generation(
                    request_id=_request_id(http_request),
                    user_id=current_user_id,
                    content_type='script',
                    action='scene',
                    input_params=request.model_dump(),
                    tool_name='script_generator',
                    tool_params={
                        'script_type': request.script_type,
                        'scene_number': request.scene_number,
                        'scene_description': request.scene_description,
                        'characters': request.characters,
                        'style': request.style,
                        'outline': request.outline,
                    },
                ),
                media_type="text/event-stream",
            )
        logger.info(f"用户 {current_user_id} 请求生成第{request.scene_number}场脚本")

        generation_id, start_time = await save_content_generation(
            user_id=current_user_id,
            content_type='script',
            action='scene',
            input_params=request.model_dump(),
            tool_name='script_generator'
        )

        tool = get_tool("script_generator")
        if not tool:
            raise HTTPException(status_code=500, detail="脚本生成工具不可用")

        result = await tool.safe_execute(
            action="scene",
            script_type=request.script_type,
            scene_number=request.scene_number,
            scene_description=request.scene_description,
            characters=request.characters,
            style=request.style,
            outline=request.outline
        )

        if generation_id:
            await update_content_generation(generation_id, start_time, result)

        if result.get('success') and result.get('data'):
            result['data']['generation_id'] = generation_id

        logger.info(f"场景脚本生成完成，成功: {result.get('success')}")
        return ContentGenerationResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成场景脚本失败: {str(e)}", exc_info=True)
        error_result = {"success": False, "data": None, "error": str(e)}

        if generation_id and start_time:
            await update_content_generation(generation_id, start_time, error_result)

        return ContentGenerationResponse(**error_result)


@router.post(
    "/script/dialogue",
    response_model=ContentGenerationResponse,
    summary="生成对白",
    description="生成脚本对白"
)
async def generate_script_dialogue(
    http_request: Request,
    request: ScriptDialogueRequest,
    stream: bool = False,
    current_user: User | Dict[str, Any] = Depends(get_current_user)
):
    """生成对白"""
    generation_id = None
    start_time = None

    try:
        current_user_id = resolve_current_user_id(current_user)
        if stream:
            return StreamingResponse(
                _stream_content_generation(
                    request_id=_request_id(http_request),
                    user_id=current_user_id,
                    content_type='script',
                    action='dialogue',
                    input_params=request.model_dump(),
                    tool_name='script_generator',
                    tool_params={
                        'script_type': request.script_type,
                        'characters': request.characters,
                        'scene_description': request.scene_description,
                        'style': request.style,
                    },
                ),
                media_type="text/event-stream",
            )
        logger.info(f"用户 {current_user_id} 请求生成对白")

        generation_id, start_time = await save_content_generation(
            user_id=current_user_id,
            content_type='script',
            action='dialogue',
            input_params=request.model_dump(),
            tool_name='script_generator'
        )

        tool = get_tool("script_generator")
        if not tool:
            raise HTTPException(status_code=500, detail="脚本生成工具不可用")

        result = await tool.safe_execute(
            action="dialogue",
            script_type=request.script_type,
            characters=request.characters,
            scene_description=request.scene_description,
            style=request.style
        )

        if generation_id:
            await update_content_generation(generation_id, start_time, result)

        if result.get('success') and result.get('data'):
            result['data']['generation_id'] = generation_id

        logger.info(f"对白生成完成，成功: {result.get('success')}")
        return ContentGenerationResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成对白失败: {str(e)}", exc_info=True)
        error_result = {"success": False, "data": None, "error": str(e)}

        if generation_id and start_time:
            await update_content_generation(generation_id, start_time, error_result)

        return ContentGenerationResponse(**error_result)


@router.post(
    "/script/storyboard",
    response_model=ContentGenerationResponse,
    summary="生成分镜脚本",
    description="生成详细的分镜脚本"
)
async def generate_script_storyboard(
    http_request: Request,
    request: ScriptStoryboardRequest,
    stream: bool = False,
    current_user: User | Dict[str, Any] = Depends(get_current_user)
):
    """生成分镜脚本"""
    generation_id = None
    start_time = None

    try:
        current_user_id = resolve_current_user_id(current_user)
        if stream:
            return StreamingResponse(
                _stream_content_generation(
                    request_id=_request_id(http_request),
                    user_id=current_user_id,
                    content_type='script',
                    action='storyboard',
                    input_params=request.model_dump(),
                    tool_name='script_generator',
                    tool_params={
                        'script_type': request.script_type,
                        'scene_description': request.scene_description,
                        'style': request.style,
                    },
                ),
                media_type="text/event-stream",
            )
        logger.info(f"用户 {current_user_id} 请求生成分镜脚本")

        generation_id, start_time = await save_content_generation(
            user_id=current_user_id,
            content_type='script',
            action='storyboard',
            input_params=request.model_dump(),
            tool_name='script_generator'
        )

        tool = get_tool("script_generator")
        if not tool:
            raise HTTPException(status_code=500, detail="脚本生成工具不可用")

        result = await tool.safe_execute(
            action="storyboard",
            script_type=request.script_type,
            scene_description=request.scene_description,
            style=request.style
        )

        if generation_id:
            await update_content_generation(generation_id, start_time, result)

        if result.get('success') and result.get('data'):
            result['data']['generation_id'] = generation_id

        logger.info(f"分镜脚本生成完成，成功: {result.get('success')}")
        return ContentGenerationResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成分镜脚本失败: {str(e)}", exc_info=True)
        error_result = {"success": False, "data": None, "error": str(e)}

        if generation_id and start_time:
            await update_content_generation(generation_id, start_time, error_result)

        return ContentGenerationResponse(**error_result)


@router.post(
    "/script/complete",
    response_model=ContentGenerationResponse,
    summary="生成完整脚本",
    description="生成完整的脚本内容"
)
async def generate_complete_script(
    http_request: Request,
    request: ScriptCompleteRequest,
    stream: bool = False,
    current_user: User | Dict[str, Any] = Depends(get_current_user)
):
    """生成完整脚本"""
    generation_id = None
    start_time = None

    try:
        current_user_id = resolve_current_user_id(current_user)
        if stream:
            return StreamingResponse(
                _stream_content_generation(
                    request_id=_request_id(http_request),
                    user_id=current_user_id,
                    content_type='script',
                    action='complete',
                    input_params=request.model_dump(),
                    tool_name='script_generator',
                    tool_params={
                        'script_type': request.script_type,
                        'title': request.title,
                        'theme': request.theme,
                        'style': request.style,
                        'duration': request.duration,
                        'target_audience': request.target_audience,
                    },
                ),
                media_type="text/event-stream",
            )
        logger.info(f"用户 {current_user_id} 请求生成完整脚本: {request.title}")

        generation_id, start_time = await save_content_generation(
            user_id=current_user_id,
            content_type='script',
            action='complete',
            input_params=request.model_dump(),
            tool_name='script_generator'
        )

        tool = get_tool("script_generator")
        if not tool:
            raise HTTPException(status_code=500, detail="脚本生成工具不可用")

        result = await tool.safe_execute(
            action="complete",
            script_type=request.script_type,
            title=request.title,
            theme=request.theme,
            style=request.style,
            duration=request.duration,
            target_audience=request.target_audience
        )

        if generation_id:
            await update_content_generation(generation_id, start_time, result)

        if result.get('success') and result.get('data'):
            result['data']['generation_id'] = generation_id

        logger.info(f"完整脚本生成完成，成功: {result.get('success')}")
        return ContentGenerationResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成完整脚本失败: {str(e)}", exc_info=True)
        error_result = {"success": False, "data": None, "error": str(e)}

        if generation_id and start_time:
            await update_content_generation(generation_id, start_time, error_result)

        return ContentGenerationResponse(**error_result)


# ==================== 内容优化API ====================

@router.post(
    "/optimize",
    response_model=ContentGenerationResponse,
    summary="优化内容",
    description="对内容进行润色、改写、扩写、缩写等优化"
)
async def optimize_content(
    http_request: Request,
    request: ContentOptimizeRequest,
    stream: bool = False,
    current_user: User | Dict[str, Any] = Depends(get_current_user)
):
    """优化内容"""
    generation_id = None
    start_time = None

    try:
        current_user_id = resolve_current_user_id(current_user)
        if stream:
            return StreamingResponse(
                _stream_content_generation(
                    request_id=_request_id(http_request),
                    user_id=current_user_id,
                    content_type='optimization',
                    action=request.action,
                    input_params=request.model_dump(),
                    tool_name='content_optimizer',
                    tool_params={
                        'content': request.content,
                        'target_style': request.target_style,
                        'target_length': request.target_length,
                        'keywords': request.keywords,
                        'requirements': request.requirements,
                    },
                ),
                media_type="text/event-stream",
            )
        logger.info(f"用户 {current_user_id} 请求优化内容，操作: {request.action}")

        generation_id, start_time = await save_content_generation(
            user_id=current_user_id,
            content_type='optimization',
            action=request.action,
            input_params=request.model_dump(),
            tool_name='content_optimizer'
        )

        tool = get_tool("content_optimizer")
        if not tool:
            raise HTTPException(status_code=500, detail="内容优化工具不可用")

        result = await tool.safe_execute(
            action=request.action,
            content=request.content,
            target_style=request.target_style,
            target_length=request.target_length,
            keywords=request.keywords,
            requirements=request.requirements
        )

        if generation_id:
            await update_content_generation(generation_id, start_time, result)

        if result.get('success') and result.get('data'):
            result['data']['generation_id'] = generation_id

        logger.info(f"内容优化完成，成功: {result.get('success')}")
        return ContentGenerationResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"优化内容失败: {str(e)}", exc_info=True)
        error_result = {"success": False, "data": None, "error": str(e)}

        if generation_id and start_time:
            await update_content_generation(generation_id, start_time, error_result)

        return ContentGenerationResponse(**error_result)
