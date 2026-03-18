from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class NovelOutlineRequest(BaseModel):
    title: Optional[str] = Field(None, description="小说标题")
    theme: Optional[str] = Field(None, description="小说主题")
    genre: Optional[str] = Field(None, description="小说类型")
    style: Optional[str] = Field(None, description="写作风格")


class NovelChapterRequest(BaseModel):
    chapter_number: int = Field(..., description="章节编号")
    chapter_title: Optional[str] = Field(None, description="章节标题")
    outline: Optional[str] = Field(None, description="小说大纲")
    genre: Optional[str] = Field(None, description="小说类型")
    style: Optional[str] = Field(None, description="写作风格")
    word_count: int = Field(2000, description="目标字数")


class NovelCharacterRequest(BaseModel):
    character_name: Optional[str] = Field(None, description="角色名称")
    genre: Optional[str] = Field(None, description="小说类型")
    theme: Optional[str] = Field(None, description="故事主题")


class NovelWorldviewRequest(BaseModel):
    title: Optional[str] = Field(None, description="小说标题")
    theme: Optional[str] = Field(None, description="故事主题")
    genre: Optional[str] = Field(None, description="小说类型")


class NovelContinueRequest(BaseModel):
    previous_content: str = Field(..., description="前文内容")
    genre: Optional[str] = Field(None, description="小说类型")
    style: Optional[str] = Field(None, description="写作风格")
    word_count: int = Field(1000, description="目标字数")


class ScriptOutlineRequest(BaseModel):
    script_type: str = Field(..., description="脚本类型")
    title: Optional[str] = Field(None, description="脚本标题")
    theme: Optional[str] = Field(None, description="脚本主题")
    style: Optional[str] = Field(None, description="脚本风格")
    duration: Optional[int] = Field(None, description="时长（分钟）")
    target_audience: Optional[str] = Field(None, description="目标受众")


class ScriptSceneRequest(BaseModel):
    script_type: str = Field(..., description="脚本类型")
    scene_number: int = Field(1, description="场景编号")
    scene_description: Optional[str] = Field(None, description="场景描述")
    characters: Optional[str] = Field(None, description="角色列表")
    style: Optional[str] = Field(None, description="脚本风格")
    outline: Optional[str] = Field(None, description="脚本大纲")


class ScriptDialogueRequest(BaseModel):
    script_type: str = Field(..., description="脚本类型")
    characters: Optional[str] = Field(None, description="角色列表")
    scene_description: Optional[str] = Field(None, description="场景描述")
    style: Optional[str] = Field(None, description="脚本风格")


class ScriptStoryboardRequest(BaseModel):
    script_type: str = Field(..., description="脚本类型")
    scene_description: Optional[str] = Field(None, description="场景描述")
    style: Optional[str] = Field(None, description="脚本风格")


class ScriptCompleteRequest(BaseModel):
    script_type: str = Field(..., description="脚本类型")
    title: Optional[str] = Field(None, description="脚本标题")
    theme: Optional[str] = Field(None, description="脚本主题")
    style: Optional[str] = Field(None, description="脚本风格")
    duration: Optional[int] = Field(None, description="时长（分钟）")
    target_audience: Optional[str] = Field(None, description="目标受众")


class ContentOptimizeRequest(BaseModel):
    action: str = Field(..., description="操作类型")
    content: str = Field(..., description="待优化内容")
    target_style: Optional[str] = Field(None, description="目标风格")
    target_length: Optional[int] = Field(None, description="目标字数")
    keywords: Optional[str] = Field(None, description="关键词")
    requirements: Optional[str] = Field(None, description="特殊要求")


class ContentGenerationResponse(BaseModel):
    success: bool = Field(..., description="是否成功")
    data: Optional[Dict[str, Any]] = Field(None, description="生成结果")
    error: Optional[str] = Field(None, description="错误信息")
