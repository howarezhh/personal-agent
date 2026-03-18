from __future__ import annotations

"""内容生成路由规格定义。"""

from dataclasses import dataclass
from typing import Any, Callable

from backend.contracts.api.content_generation import (
    ContentOptimizeRequest,
    NovelChapterRequest,
    NovelCharacterRequest,
    NovelContinueRequest,
    NovelOutlineRequest,
    NovelWorldviewRequest,
    ScriptCompleteRequest,
    ScriptDialogueRequest,
    ScriptOutlineRequest,
    ScriptSceneRequest,
    ScriptStoryboardRequest,
)


ToolParamsBuilder = Callable[[Any], dict[str, Any]]
ActionBuilder = Callable[[Any], str]


@dataclass(frozen=True)
class ContentGenerationRouteSpec:
    """内容生成单个路由的唯一规格定义。"""

    path: str
    endpoint_name: str
    request_model: type
    content_type: str
    action: str | ActionBuilder
    tool_name: str
    summary: str
    description: str
    log_label: str
    tool_params_builder: ToolParamsBuilder

    def resolve_action(self, request_model: Any) -> str:
        """解析当前请求对应的动作名。"""
        if callable(self.action):
            return self.action(request_model)
        return self.action

    def build_tool_params(self, request_model: Any) -> dict[str, Any]:
        """根据请求对象构造工具调用参数。"""
        return self.tool_params_builder(request_model)


CONTENT_GENERATION_ROUTE_SPECS = (
    ContentGenerationRouteSpec(
        path="/novel/outline",
        endpoint_name="generate_novel_outline",
        request_model=NovelOutlineRequest,
        content_type="novel",
        action="outline",
        tool_name="novel_generator",
        summary="Generate novel outline",
        description="Generate a novel outline from title and theme.",
        log_label="generate_novel_outline",
        tool_params_builder=lambda request: {
            "title": request.title,
            "theme": request.theme,
            "genre": request.genre,
            "style": request.style,
        },
    ),
    ContentGenerationRouteSpec(
        path="/novel/chapter",
        endpoint_name="generate_novel_chapter",
        request_model=NovelChapterRequest,
        content_type="novel",
        action="chapter",
        tool_name="novel_generator",
        summary="Generate novel chapter",
        description="Generate chapter content for a novel.",
        log_label="generate_novel_chapter",
        tool_params_builder=lambda request: {
            "chapter_number": request.chapter_number,
            "chapter_title": request.chapter_title,
            "outline": request.outline,
            "genre": request.genre,
            "style": request.style,
            "word_count": request.word_count,
        },
    ),
    ContentGenerationRouteSpec(
        path="/novel/character",
        endpoint_name="generate_novel_character",
        request_model=NovelCharacterRequest,
        content_type="novel",
        action="character",
        tool_name="novel_generator",
        summary="Generate novel character",
        description="Generate a character profile for a novel.",
        log_label="generate_novel_character",
        tool_params_builder=lambda request: {
            "character_name": request.character_name,
            "genre": request.genre,
            "theme": request.theme,
        },
    ),
    ContentGenerationRouteSpec(
        path="/novel/worldview",
        endpoint_name="generate_novel_worldview",
        request_model=NovelWorldviewRequest,
        content_type="novel",
        action="worldview",
        tool_name="novel_generator",
        summary="Generate novel worldview",
        description="Generate a worldview for a novel.",
        log_label="generate_novel_worldview",
        tool_params_builder=lambda request: {
            "title": request.title,
            "theme": request.theme,
            "genre": request.genre,
        },
    ),
    ContentGenerationRouteSpec(
        path="/novel/continue",
        endpoint_name="continue_novel",
        request_model=NovelContinueRequest,
        content_type="novel",
        action="continue",
        tool_name="novel_generator",
        summary="Continue novel content",
        description="Continue writing from previous novel content.",
        log_label="continue_novel",
        tool_params_builder=lambda request: {
            "previous_content": request.previous_content,
            "genre": request.genre,
            "style": request.style,
            "word_count": request.word_count,
        },
    ),
    ContentGenerationRouteSpec(
        path="/script/outline",
        endpoint_name="generate_script_outline",
        request_model=ScriptOutlineRequest,
        content_type="script",
        action="outline",
        tool_name="script_generator",
        summary="Generate script outline",
        description="Generate an outline for a script.",
        log_label="generate_script_outline",
        tool_params_builder=lambda request: {
            "script_type": request.script_type,
            "title": request.title,
            "theme": request.theme,
            "style": request.style,
            "duration": request.duration,
            "target_audience": request.target_audience,
        },
    ),
    ContentGenerationRouteSpec(
        path="/script/scene",
        endpoint_name="generate_script_scene",
        request_model=ScriptSceneRequest,
        content_type="script",
        action="scene",
        tool_name="script_generator",
        summary="Generate script scene",
        description="Generate scene content for a script.",
        log_label="generate_script_scene",
        tool_params_builder=lambda request: {
            "script_type": request.script_type,
            "scene_number": request.scene_number,
            "scene_description": request.scene_description,
            "characters": request.characters,
            "style": request.style,
            "outline": request.outline,
        },
    ),
    ContentGenerationRouteSpec(
        path="/script/dialogue",
        endpoint_name="generate_script_dialogue",
        request_model=ScriptDialogueRequest,
        content_type="script",
        action="dialogue",
        tool_name="script_generator",
        summary="Generate script dialogue",
        description="Generate dialogue for a script scene.",
        log_label="generate_script_dialogue",
        tool_params_builder=lambda request: {
            "script_type": request.script_type,
            "characters": request.characters,
            "scene_description": request.scene_description,
            "style": request.style,
        },
    ),
    ContentGenerationRouteSpec(
        path="/script/storyboard",
        endpoint_name="generate_script_storyboard",
        request_model=ScriptStoryboardRequest,
        content_type="script",
        action="storyboard",
        tool_name="script_generator",
        summary="Generate script storyboard",
        description="Generate storyboard content for a script.",
        log_label="generate_script_storyboard",
        tool_params_builder=lambda request: {
            "script_type": request.script_type,
            "scene_description": request.scene_description,
            "style": request.style,
        },
    ),
    ContentGenerationRouteSpec(
        path="/script/complete",
        endpoint_name="generate_complete_script",
        request_model=ScriptCompleteRequest,
        content_type="script",
        action="complete",
        tool_name="script_generator",
        summary="Generate complete script",
        description="Generate a complete script.",
        log_label="generate_complete_script",
        tool_params_builder=lambda request: {
            "script_type": request.script_type,
            "title": request.title,
            "theme": request.theme,
            "style": request.style,
            "duration": request.duration,
            "target_audience": request.target_audience,
        },
    ),
    ContentGenerationRouteSpec(
        path="/optimize",
        endpoint_name="optimize_content",
        request_model=ContentOptimizeRequest,
        content_type="optimization",
        action=lambda request: request.action,
        tool_name="content_optimizer",
        summary="Optimize content",
        description="Optimize or rewrite existing content.",
        log_label="optimize_content",
        tool_params_builder=lambda request: {
            "content": request.content,
            "target_style": request.target_style,
            "target_length": request.target_length,
            "keywords": request.keywords,
            "requirements": request.requirements,
        },
    ),
)
