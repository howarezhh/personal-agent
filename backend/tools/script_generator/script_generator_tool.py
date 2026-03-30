
from typing import AsyncGenerator, Dict, Any, Optional
from backend.tools.base_tool import BaseTool, ToolDefinition, ToolParameter
from backend.core.config_manager import get_config_manager
from backend.core.prompt_manager import get_prompt_manager
import logging
import json

from pydantic import BaseModel, ConfigDict


class _ScriptStructuredPayloadBase(BaseModel):
    """用于承接脚本结构化输出的基础模型。"""

    model_config = ConfigDict(extra="allow")


class ScriptOutlineStructuredPayload(_ScriptStructuredPayloadBase):
    raw_outline: Optional[str] = None


class ScriptStoryboardStructuredPayload(_ScriptStructuredPayloadBase):
    raw_storyboard: Optional[str] = None


class ScriptGeneratorTool(BaseTool):
    declared_capabilities = ("invoke", "stream", "local_direct")
    STRUCTURED_OUTPUT_SCHEMAS = {
        "raw_outline": ScriptOutlineStructuredPayload,
        "raw_storyboard": ScriptStoryboardStructuredPayload,
    }

    # 脚本类型
    SCRIPT_TYPES = {
        "movie": "鐢靛奖鍓ф湰",
        "tv_series": "电视剧剧本",
        "short_video": "短视频脚本",
        "advertisement": "广告脚本",
        "stage_play": "舞台剧脚本",
        "animation": "动画脚本",
        "documentary": "纪录片脚本",
        "variety_show": "综艺节目脚本"
    }

    # 脚本风格
    SCRIPT_STYLES = {
        "comedy": "鍠滃墽",
        "drama": "鍓ф儏",
        "action": "动作",
        "romance": "鐖辨儏",
        "thriller": "鎯婃倸",
        "scifi": "科幻",
        "fantasy": "濂囧够",
        "documentary": "绾疄"
    }

    def __init__(self):
        super().__init__()
        self.config_manager = get_config_manager()
        self.prompt_manager = get_prompt_manager()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("脚本生成工具初始化完成")

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="script_generator",
            description="AI 脚本生成工具，支持生成影视剧本、短视频脚本、广告脚本等各类脚本",
            category="creative",
            strict_validation=True,
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="操作类型：outline(生成大纲)、scene(生成场景)、dialogue(生成对白)、storyboard(生成分镜)",
                    required=True,
                    enum=["outline", "scene", "dialogue", "storyboard", "complete"]
                ),
                ToolParameter(
                    name="script_type",
                    type="string",
                    description="脚本类型",
                    required=True,
                    enum=list(self.SCRIPT_TYPES.keys())
                ),
                ToolParameter(
                    name="style",
                    type="string",
                    description="脚本风格",
                    required=False,
                    enum=list(self.SCRIPT_STYLES.keys())
                ),
                ToolParameter(
                    name="title",
                    type="string",
                    description="脚本标题",
                    required=False
                ),
                ToolParameter(
                    name="theme",
                    type="string",
                    description="脚本主题或简介",
                    required=False
                ),
                ToolParameter(
                    name="duration",
                    type="integer",
                    description="鏃堕暱锛堝垎閽燂級",
                    required=False
                ),
                ToolParameter(
                    name="scene_number",
                    type="integer",
                    description="场景编号",
                    required=False
                ),
                ToolParameter(
                    name="scene_description",
                    type="string",
                    description="场景描述",
                    required=False
                ),
                ToolParameter(
                    name="characters",
                    type="string",
                    description="角色列表（逗号分隔）",
                    required=False
                ),
                ToolParameter(
                    name="target_audience",
                    type="string",
                    description="目标受众",
                    required=False
                ),
                ToolParameter(
                    name="outline",
                    type="string",
                    description="脚本大纲",
                    required=False
                )
            ],
            timeout=120
        )

    async def execute(self, action: str, script_type: str, **kwargs) -> Dict[str, Any]:
        try:
            self.logger.info(f"执行脚本生成操作: {action}, 类型: {script_type}")

            if action == "outline":
                return await self._generate_outline(
                    script_type,
                    kwargs.get("title"),
                    kwargs.get("theme"),
                    kwargs.get("style"),
                    kwargs.get("duration"),
                    kwargs.get("target_audience")
                )
            elif action == "scene":
                return await self._generate_scene(
                    script_type,
                    kwargs.get("scene_number", 1),
                    kwargs.get("scene_description"),
                    kwargs.get("characters"),
                    kwargs.get("style"),
                    kwargs.get("outline")
                )
            elif action == "dialogue":
                return await self._generate_dialogue(
                    script_type,
                    kwargs.get("characters"),
                    kwargs.get("scene_description"),
                    kwargs.get("style")
                )
            elif action == "storyboard":
                return await self._generate_storyboard(
                    script_type,
                    kwargs.get("scene_description"),
                    kwargs.get("style")
                )
            elif action == "complete":
                return await self._generate_complete_script(
                    script_type,
                    kwargs.get("title"),
                    kwargs.get("theme"),
                    kwargs.get("style"),
                    kwargs.get("duration"),
                    kwargs.get("target_audience")
                )
            else:
                return {
                    "success": False,
                    "data": None,
                    "error": f"不支持的操作类型: {action}"
                }

        except Exception as e:
            self.logger.error(f"脚本生成失败: {str(e)}", exc_info=True)
            return {
                "success": False,
                "data": None,
                "error": f"生成失败: {str(e)}"
            }

    def _get_type_name(self, script_type: str) -> str:
        return self.SCRIPT_TYPES.get(script_type, script_type)

    def _get_style_name(self, style: Optional[str]) -> str:
        return self.SCRIPT_STYLES.get(style, "默认") if style else "默认"

    def _parse_json_response(self, response: str, raw_key: str) -> Dict[str, Any]:
        # Parse structured JSON output when available.
        schema_cls = self.STRUCTURED_OUTPUT_SCHEMAS.get(raw_key)
        if schema_cls is None:
            return {raw_key: response}

        try:
            from backend.core.llm_manager import get_langchain_model_manager

            return {raw_key: response}
        except Exception:
            self.logger.debug("Failed to preserve structured streaming script response", exc_info=True)
            return {raw_key: response}

    async def execute_stream(self, action: str, script_type: str, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
        try:
            self.logger.info(f"执行脚本流式生成操作: {action}, 类型: {script_type}")

            if action == "outline":
                async for event in self._stream_outline(
                    script_type,
                    kwargs.get("title"),
                    kwargs.get("theme"),
                    kwargs.get("style"),
                    kwargs.get("duration"),
                    kwargs.get("target_audience")
                ):
                    yield event
            elif action == "scene":
                async for event in self._stream_scene(
                    script_type,
                    kwargs.get("scene_number", 1),
                    kwargs.get("scene_description"),
                    kwargs.get("characters"),
                    kwargs.get("style"),
                    kwargs.get("outline")
                ):
                    yield event
            elif action == "dialogue":
                async for event in self._stream_dialogue(
                    script_type,
                    kwargs.get("characters"),
                    kwargs.get("scene_description"),
                    kwargs.get("style")
                ):
                    yield event
            elif action == "storyboard":
                async for event in self._stream_storyboard(
                    script_type,
                    kwargs.get("scene_description"),
                    kwargs.get("style")
                ):
                    yield event
            elif action == "complete":
                async for event in self._stream_complete_script(
                    script_type,
                    kwargs.get("title"),
                    kwargs.get("theme"),
                    kwargs.get("style"),
                    kwargs.get("duration"),
                    kwargs.get("target_audience")
                ):
                    yield event
            else:
                yield {"type": "error", "error": f"不支持的操作类型: {action}"}
        except Exception as e:
            self.logger.error(f"脚本流式生成失败: {str(e)}", exc_info=True)
            yield {"type": "error", "error": f"生成失败: {str(e)}"}

    async def _stream_outline(
        self,
        script_type: str,
        title: Optional[str],
        theme: Optional[str],
        style: Optional[str],
        duration: Optional[int],
        target_audience: Optional[str],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()
        type_name = self._get_type_name(script_type)
        style_name = self._get_style_name(style)
        prompt_template = self.prompt_manager.get_prompt_template(
            "tool.script_generator_outline_prompt"
        )

        response = ""
        async for chunk in llm_manager.stream_prompt_template(
            prompt_template,
            {
                "title": title or "未命名脚本",
                "type_name": type_name,
                "style_name": style_name,
                "duration": duration or "未指定",
                "target_audience": target_audience or "泛受众",
                "theme": theme or "请生成完整脚本大纲",
            },
            temperature=0.8
        ):
            response += chunk
            yield {"type": "content", "content": chunk}

        yield {
            "type": "result",
            "data": {
                "title": title,
                "script_type": type_name,
                "style": style_name,
                "duration": duration,
                "outline": self._parse_json_response(response, "raw_outline"),
            },
        }

    async def _stream_scene(
        self,
        script_type: str,
        scene_number: int,
        scene_description: Optional[str],
        characters: Optional[str],
        style: Optional[str],
        outline: Optional[str],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()
        type_name = self._get_type_name(script_type)
        style_name = self._get_style_name(style)
        prompt_template = self.prompt_manager.get_prompt_template(
            "tool.script_generator_scene_prompt"
        )

        response = ""
        async for chunk in llm_manager.stream_prompt_template(
            prompt_template,
            {
                "type_name": type_name,
                "scene_number": scene_number,
                "scene_description": scene_description or "请根据项目目标生成场景",
                "characters": characters or "未指定角色",
                "style_name": style_name,
                "outline_text": outline or "请保持剧情连贯",
            },
            temperature=0.8, max_tokens=3000
        ):
            response += chunk
            yield {"type": "content", "content": chunk}

        yield {
            "type": "result",
            "data": {
                "scene_number": scene_number,
                "script_type": type_name,
                "style": style_name,
                "content": response,
            },
        }

    async def _stream_dialogue(
        self,
        script_type: str,
        characters: Optional[str],
        scene_description: Optional[str],
        style: Optional[str],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()
        type_name = self._get_type_name(script_type)
        style_name = self._get_style_name(style)
        prompt_template = self.prompt_manager.get_prompt_template(
            "tool.script_generator_dialogue_prompt"
        )

        response = ""
        async for chunk in llm_manager.stream_prompt_template(
            prompt_template,
            {
                "type_name": type_name,
                "characters": characters or "未指定角色",
                "scene_description": scene_description or "璇风敓鎴愮鍚堝墽鎯呯殑瀵圭櫧",
                "style_name": style_name,
            },
            temperature=0.8, max_tokens=2500
        ):
            response += chunk
            yield {"type": "content", "content": chunk}

        yield {
            "type": "result",
            "data": {
                "script_type": type_name,
                "style": style_name,
                "content": response,
                "characters": characters,
            },
        }

    async def _stream_storyboard(
        self,
        script_type: str,
        scene_description: Optional[str],
        style: Optional[str],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()
        type_name = self._get_type_name(script_type)
        style_name = self._get_style_name(style)
        prompt_template = self.prompt_manager.get_prompt_template(
            "tool.script_generator_storyboard_prompt"
        )

        response = ""
        async for chunk in llm_manager.stream_prompt_template(
            prompt_template,
            {
                "type_name": type_name,
                "scene_description": scene_description or "璇锋媶鍒嗗嚭瀹屾暣鍒嗛暅",
                "style_name": style_name,
            },
            temperature=0.8
        ):
            response += chunk
            yield {"type": "content", "content": chunk}

        yield {
            "type": "result",
            "data": {
                "script_type": type_name,
                "style": style_name,
                "storyboard": self._parse_json_response(response, "raw_storyboard"),
            },
        }

    async def _stream_complete_script(
        self,
        script_type: str,
        title: Optional[str],
        theme: Optional[str],
        style: Optional[str],
        duration: Optional[int],
        target_audience: Optional[str],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()
        type_name = self._get_type_name(script_type)
        style_name = self._get_style_name(style)
        prompt_template = self.prompt_manager.get_prompt_template(
            "tool.script_generator_complete_prompt"
        )

        response = ""
        async for chunk in llm_manager.stream_prompt_template(
            prompt_template,
            {
                "title": title or "未命名脚本",
                "type_name": type_name,
                "style_name": style_name,
                "duration": duration or "未指定",
                "target_audience": target_audience or "泛受众",
                "theme": theme or "请生成完整脚本",
            },
            temperature=0.8, max_tokens=4000
        ):
            response += chunk
            yield {"type": "content", "content": chunk}

        yield {
            "type": "result",
            "data": {
                "title": title,
                "script_type": type_name,
                "style": style_name,
                "duration": duration,
                "target_audience": target_audience,
                "content": response,
            },
        }

    async def _generate_outline(self, script_type: str, title: Optional[str],
                              theme: Optional[str], style: Optional[str],
                              duration: Optional[int], target_audience: Optional[str]) -> Dict[str, Any]:
        try:
            from backend.core.llm_manager import get_langchain_model_manager

            llm_manager = get_langchain_model_manager()

            type_name = self.SCRIPT_TYPES.get(script_type, script_type)
            style_name = self.SCRIPT_STYLES.get(style, "默认") if style else "默认"

            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.script_generator_outline_prompt"
            )

            structured_result = await llm_manager.with_structured_output(
                ScriptOutlineStructuredPayload
            ).invoke_prompt_template(
                prompt_template,
                {
                    "title": title or "未命名脚本",
                    "type_name": type_name,
                    "style_name": style_name,
                    "duration": duration or "未指定",
                    "target_audience": target_audience or "泛受众",
                    "theme": theme or "请生成完整脚本大纲",
                },
                temperature=0.8,
            )
            outline_data = structured_result.model_dump(exclude_none=True)

            self.logger.info("脚本大纲生成完成")
            return {
                "success": True,
                "data": {
                    "title": title,
                    "script_type": type_name,
                    "style": style_name,
                    "duration": duration,
                    "outline": outline_data,
                },
                "error": None,
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"生成大纲失败: {str(e)}",
            }
    async def _generate_scene(self, script_type: str, scene_number: int,
                             scene_description: Optional[str], characters: Optional[str],
                             style: Optional[str], outline: Optional[str]) -> Dict[str, Any]:
        try:
            from backend.core.llm_manager import get_langchain_model_manager

            llm_manager = get_langchain_model_manager()

            type_name = self.SCRIPT_TYPES.get(script_type, script_type)
            style_name = self.SCRIPT_STYLES.get(style, "默认") if style else "默认"

            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.script_generator_scene_prompt"
            )

            response = await llm_manager.invoke_prompt_template(
                prompt_template,
                {
                    "type_name": type_name,
                    "scene_number": scene_number,
                    "scene_description": scene_description or "请根据项目目标生成场景",
                    "characters": characters or "未指定角色",
                    "style_name": style_name,
                    "outline_text": outline or "请保持剧情连贯",
                },
                temperature=0.8,
                max_tokens=3000,
            )
            response_text = str(response or "")

            self.logger.info("场景生成完成: scene=%s", scene_number)
            return {
                "success": True,
                "data": {
                    "scene_number": scene_number,
                    "script_type": type_name,
                    "style": style_name,
                    "content": response_text,
                },
                "error": None,
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"生成场景失败: {str(e)}",
            }
    async def _generate_dialogue(self, script_type: str, characters: Optional[str],
                                scene_description: Optional[str], style: Optional[str]) -> Dict[str, Any]:
        try:
            from backend.core.llm_manager import get_langchain_model_manager

            llm_manager = get_langchain_model_manager()

            type_name = self.SCRIPT_TYPES.get(script_type, script_type)
            style_name = self.SCRIPT_STYLES.get(style, "默认") if style else "默认"

            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.script_generator_dialogue_prompt"
            )

            response = await llm_manager.invoke_prompt_template(
                prompt_template,
                {
                    "type_name": type_name,
                    "scene_description": scene_description or "璇风敓鎴愮鍚堝墽鎯呯殑瀵圭櫧",
                    "characters": characters or "未指定角色",
                    "style_name": style_name,
                },
                temperature=0.8, max_tokens=2000,
            )

            self.logger.info("对白生成完成")

            return {
                "success": True,
                "data": {
                    "script_type": type_name,
                    "style": style_name,
                    "dialogue": response
                },
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"生成对白失败: {str(e)}"
            }

    async def _generate_storyboard(self, script_type: str, scene_description: Optional[str],
                                  style: Optional[str]) -> Dict[str, Any]:
        try:
            from backend.core.llm_manager import get_langchain_model_manager

            llm_manager = get_langchain_model_manager()

            type_name = self.SCRIPT_TYPES.get(script_type, script_type)
            style_name = self.SCRIPT_STYLES.get(style, "默认") if style else "默认"

            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.script_generator_storyboard_prompt"
            )

            structured_result = await llm_manager.with_structured_output(
                ScriptStoryboardStructuredPayload
            ).invoke_prompt_template(
                prompt_template,
                {
                    "type_name": type_name,
                    "scene_description": scene_description or "请生成分镜描述",
                    "style_name": style_name,
                },
                temperature=0.8,
            )
            storyboard_data = structured_result.model_dump(exclude_none=True)

            self.logger.info("分镜脚本生成完成")
            return {
                "success": True,
                "data": {
                    "script_type": type_name,
                    "style": style_name,
                    "storyboard": storyboard_data,
                },
                "error": None,
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"生成分镜脚本失败: {str(e)}",
            }
    async def _generate_complete_script(self, script_type: str, title: Optional[str],
                                       theme: Optional[str], style: Optional[str],
                                       duration: Optional[int], target_audience: Optional[str]) -> Dict[str, Any]:
        try:
            outline_result = await self._generate_outline(
                script_type, title, theme, style, duration, target_audience
            )
            if not outline_result["success"]:
                return outline_result

            from backend.core.llm_manager import get_langchain_model_manager

            llm_manager = get_langchain_model_manager()

            type_name = self.SCRIPT_TYPES.get(script_type, script_type)
            style_name = self.SCRIPT_STYLES.get(style, "默认") if style else "默认"
            outline_str = json.dumps(outline_result["data"]["outline"], ensure_ascii=False, indent=2)

            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.script_generator_complete_prompt"
            )

            response = await llm_manager.invoke_prompt_template(
                prompt_template,
                {
                    "title": title or "未命名脚本",
                    "type_name": type_name,
                    "style_name": style_name,
                    "duration": duration or "未指定",
                    "outline_json": outline_str,
                },
                temperature=0.8,
                max_tokens=4000,
            )

            self.logger.info("完整脚本生成完成")
            return {
                "success": True,
                "data": {
                    "title": title,
                    "script_type": type_name,
                    "style": style_name,
                    "duration": duration,
                    "outline": outline_result["data"]["outline"],
                    "complete_script": str(response or ""),
                },
                "error": None,
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"生成完整脚本失败: {str(e)}",
            }
    def get_supported_types(self) -> Dict[str, str]:
        return self.SCRIPT_TYPES.copy()

    def get_supported_styles(self) -> Dict[str, str]:
        return self.SCRIPT_STYLES.copy()


