"""
内容生成API
提供小说生成、脚本生成、内容优化等接口
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import time
import json
import uuid
from backend.tools.tool_registry import get_tool
from backend.api.dependencies import get_current_user
from backend.utils.logger import get_logger
from backend.database.database_manager import get_database_manager

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/content",
    tags=["内容生成"]
)


# ==================== 辅助函数 ====================

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
        db_manager = get_database_manager()
        db_manager.execute_query(
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
            ),
            fetch=False
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
        db_manager = get_database_manager()

        if result.get('success'):
            db_manager.execute_query(
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
                ),
                fetch=False
            )
            logger.info(f"内容生成完成，ID: {generation_id}, 执行时间: {execution_time}ms")
        else:
            db_manager.execute_query(
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
                ),
                fetch=False
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
    request: NovelOutlineRequest,
    current_user: dict = Depends(get_current_user)
):
    """生成小说大纲"""
    generation_id = None
    start_time = None

    try:
        logger.info(f"用户 {current_user.get('user_id')} 请求生成小说大纲: {request.title}")

        # 保存生成记录（pending状态）
        generation_id, start_time = await save_content_generation(
            user_id=current_user.get('user_id'),
            content_type='novel',
            action='outline',
            input_params=request.dict(),
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
    request: NovelChapterRequest,
    current_user: dict = Depends(get_current_user)
):
    """生成小说章节"""
    generation_id = None
    start_time = None

    try:
        logger.info(f"用户 {current_user.get('user_id')} 请求生成第{request.chapter_number}章")

        # 保存生成记录
        generation_id, start_time = await save_content_generation(
            user_id=current_user.get('user_id'),
            content_type='novel',
            action='chapter',
            input_params=request.dict(),
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
    request: NovelCharacterRequest,
    current_user: dict = Depends(get_current_user)
):
    """生成角色设定"""
    generation_id = None
    start_time = None

    try:
        logger.info(f"用户 {current_user.get('user_id')} 请求生成角色设定: {request.character_name}")

        generation_id, start_time = await save_content_generation(
            user_id=current_user.get('user_id'),
            content_type='novel',
            action='character',
            input_params=request.dict(),
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
    request: NovelWorldviewRequest,
    current_user: dict = Depends(get_current_user)
):
    """生成世界观设定"""
    generation_id = None
    start_time = None

    try:
        logger.info(f"用户 {current_user.get('user_id')} 请求生成世界观设定")

        generation_id, start_time = await save_content_generation(
            user_id=current_user.get('user_id'),
            content_type='novel',
            action='worldview',
            input_params=request.dict(),
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
    request: NovelContinueRequest,
    current_user: dict = Depends(get_current_user)
):
    """续写小说"""
    generation_id = None
    start_time = None

    try:
        logger.info(f"用户 {current_user.get('user_id')} 请求续写小说")

        generation_id, start_time = await save_content_generation(
            user_id=current_user.get('user_id'),
            content_type='novel',
            action='continue',
            input_params=request.dict(),
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
    request: ScriptOutlineRequest,
    current_user: dict = Depends(get_current_user)
):
    """生成脚本大纲"""
    generation_id = None
    start_time = None

    try:
        logger.info(f"用户 {current_user.get('user_id')} 请求生成脚本大纲: {request.title}")

        generation_id, start_time = await save_content_generation(
            user_id=current_user.get('user_id'),
            content_type='script',
            action='outline',
            input_params=request.dict(),
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
    request: ScriptSceneRequest,
    current_user: dict = Depends(get_current_user)
):
    """生成场景脚本"""
    generation_id = None
    start_time = None

    try:
        logger.info(f"用户 {current_user.get('user_id')} 请求生成第{request.scene_number}场脚本")

        generation_id, start_time = await save_content_generation(
            user_id=current_user.get('user_id'),
            content_type='script',
            action='scene',
            input_params=request.dict(),
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
    request: ScriptDialogueRequest,
    current_user: dict = Depends(get_current_user)
):
    """生成对白"""
    generation_id = None
    start_time = None

    try:
        logger.info(f"用户 {current_user.get('user_id')} 请求生成对白")

        generation_id, start_time = await save_content_generation(
            user_id=current_user.get('user_id'),
            content_type='script',
            action='dialogue',
            input_params=request.dict(),
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
    request: ScriptStoryboardRequest,
    current_user: dict = Depends(get_current_user)
):
    """生成分镜脚本"""
    generation_id = None
    start_time = None

    try:
        logger.info(f"用户 {current_user.get('user_id')} 请求生成分镜脚本")

        generation_id, start_time = await save_content_generation(
            user_id=current_user.get('user_id'),
            content_type='script',
            action='storyboard',
            input_params=request.dict(),
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
    request: ScriptCompleteRequest,
    current_user: dict = Depends(get_current_user)
):
    """生成完整脚本"""
    generation_id = None
    start_time = None

    try:
        logger.info(f"用户 {current_user.get('user_id')} 请求生成完整脚本: {request.title}")

        generation_id, start_time = await save_content_generation(
            user_id=current_user.get('user_id'),
            content_type='script',
            action='complete',
            input_params=request.dict(),
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
    request: ContentOptimizeRequest,
    current_user: dict = Depends(get_current_user)
):
    """优化内容"""
    generation_id = None
    start_time = None

    try:
        logger.info(f"用户 {current_user.get('user_id')} 请求优化内容，操作: {request.action}")

        generation_id, start_time = await save_content_generation(
            user_id=current_user.get('user_id'),
            content_type='optimization',
            action=request.action,
            input_params=request.dict(),
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
