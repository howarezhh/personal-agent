
from typing import AsyncGenerator, Dict, Any, Optional, List
from backend.tools.base_tool import BaseTool, ToolDefinition, ToolParameter
from backend.core.config_manager import get_config_manager
from backend.core.prompt_manager import get_prompt_manager
import logging
import json

from pydantic import BaseModel, ConfigDict


class _NovelStructuredPayloadBase(BaseModel):
    """用于承接小说结构化输出的基础模型。"""

    model_config = ConfigDict(extra="allow")


class NovelOutlineStructuredPayload(_NovelStructuredPayloadBase):
    raw_outline: Optional[str] = None


class NovelCharacterStructuredPayload(_NovelStructuredPayloadBase):
    raw_character: Optional[str] = None


class NovelWorldviewStructuredPayload(_NovelStructuredPayloadBase):
    raw_worldview: Optional[str] = None


class NovelGeneratorTool(BaseTool):
    declared_capabilities = ("invoke", "stream", "local_direct")
    STRUCTURED_OUTPUT_SCHEMAS = {
        "raw_outline": NovelOutlineStructuredPayload,
        "raw_character": NovelCharacterStructuredPayload,
        "raw_worldview": NovelWorldviewStructuredPayload,
    }

    # 灏忚绫诲瀷
    NOVEL_GENRES = {
        "fantasy": "鐜勫够",
        "urban": "閮藉競",
        "romance": "言情",
        "scifi": "科幻",
        "wuxia": "姝︿緺",
        "xianxia": "浠欎緺",
        "history": "鍘嗗彶",
        "military": "鍐涗簨",
        "mystery": "鎮枒",
        "horror": "恐怖",
        "game": "娓告垙",
        "sports": "浣撹偛",
        "fanfic": "鍚屼汉"
    }

    # 鍐欎綔椋庢牸
    WRITING_STYLES = {
        "descriptive": "描写细腻",
        "concise": "简洁明快",
        "humorous": "幽默风趣",
        "serious": "严谨正式",
        "poetic": "诗意优美",
        "suspenseful": "鎮康杩捣"
    }

    def __init__(self):
        super().__init__()
        self.config_manager = get_config_manager()
        self.prompt_manager = get_prompt_manager()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("小说生成工具初始化完成")

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="novel_generator",
            description="AI 小说生成工具，支持生成小说大纲、章节内容、角色设定和世界观设定",
            category="creative",
            strict_validation=True,
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="操作类型：outline(生成大纲)、chapter(生成章节)、character(生成角色)、worldview(生成世界观)、continue(续写)",
                    required=True,
                    enum=["outline", "chapter", "character", "worldview", "continue"]
                ),
                ToolParameter(
                    name="genre",
                    type="string",
                    description="灏忚绫诲瀷",
                    required=False,
                    enum=list(self.NOVEL_GENRES.keys())
                ),
                ToolParameter(
                    name="style",
                    type="string",
                    description="鍐欎綔椋庢牸",
                    required=False,
                    enum=list(self.WRITING_STYLES.keys())
                ),
                ToolParameter(
                    name="title",
                    type="string",
                    description="灏忚鏍囬",
                    required=False
                ),
                ToolParameter(
                    name="theme",
                    type="string",
                    description="小说主题或简介",
                    required=False
                ),
                ToolParameter(
                    name="chapter_number",
                    type="integer",
                    description="绔犺妭缂栧彿",
                    required=False
                ),
                ToolParameter(
                    name="chapter_title",
                    type="string",
                    description="绔犺妭鏍囬",
                    required=False
                ),
                ToolParameter(
                    name="previous_content",
                    type="string",
                    description="鍓嶆枃鍐呭锛堢敤浜庣画鍐欙級",
                    required=False
                ),
                ToolParameter(
                    name="character_name",
                    type="string",
                    description="瑙掕壊鍚嶇О",
                    required=False
                ),
                ToolParameter(
                    name="word_count",
                    type="integer",
                    description="目标字数",
                    required=False,
                    default=2000
                ),
                ToolParameter(
                    name="outline",
                    type="string",
                    description="灏忚澶х翰锛堢敤浜庣敓鎴愮珷鑺傦級",
                    required=False
                )
            ],
            timeout=120
        )

    async def execute(self, action: str, **kwargs) -> Dict[str, Any]:
        try:
            self.logger.info(f"执行小说生成操作: {action}")

            if action == "outline":
                return await self._generate_outline(
                    kwargs.get("title"),
                    kwargs.get("theme"),
                    kwargs.get("genre"),
                    kwargs.get("style")
                )
            elif action == "chapter":
                return await self._generate_chapter(
                    kwargs.get("chapter_number", 1),
                    kwargs.get("chapter_title"),
                    kwargs.get("outline"),
                    kwargs.get("genre"),
                    kwargs.get("style"),
                    kwargs.get("word_count", 2000)
                )
            elif action == "character":
                return await self._generate_character(
                    kwargs.get("character_name"),
                    kwargs.get("genre"),
                    kwargs.get("theme")
                )
            elif action == "worldview":
                return await self._generate_worldview(
                    kwargs.get("title"),
                    kwargs.get("theme"),
                    kwargs.get("genre")
                )
            elif action == "continue":
                return await self._continue_writing(
                    kwargs.get("previous_content"),
                    kwargs.get("genre"),
                    kwargs.get("style"),
                    kwargs.get("word_count", 1000)
                )
            else:
                return {
                    "success": False,
                    "data": None,
                    "error": f"不支持的操作类型: {action}"
                }

        except Exception as e:
            self.logger.error(f"小说生成失败: {str(e)}", exc_info=True)
            return {
                "success": False,
                "data": None,
                "error": f"生成失败: {str(e)}"
            }

    def _get_genre_name(self, genre: Optional[str]) -> str:
        return self.NOVEL_GENRES.get(genre, "鏈煡") if genre else "鏈煡"

    def _get_style_name(self, style: Optional[str]) -> str:
        return self.WRITING_STYLES.get(style, "默认") if style else "默认"

    def _parse_json_response(self, response: str, raw_key: str) -> Dict[str, Any]:
        # Parse structured JSON output when available.
        schema_cls = self.STRUCTURED_OUTPUT_SCHEMAS.get(raw_key)
        if schema_cls is None:
            return {raw_key: response}

        try:
            from backend.core.llm_manager import get_langchain_model_manager

            return {raw_key: response}
        except Exception:
            self.logger.debug("Failed to preserve structured streaming response", exc_info=True)
            return {raw_key: response}

    async def execute_stream(self, action: str, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
        try:
            self.logger.info(f"执行小说流式生成操作: {action}")

            if action == "outline":
                async for event in self._stream_outline(
                    kwargs.get("title"),
                    kwargs.get("theme"),
                    kwargs.get("genre"),
                    kwargs.get("style")
                ):
                    yield event
            elif action == "chapter":
                async for event in self._stream_chapter(
                    kwargs.get("chapter_number", 1),
                    kwargs.get("chapter_title"),
                    kwargs.get("outline"),
                    kwargs.get("genre"),
                    kwargs.get("style"),
                    kwargs.get("word_count", 2000)
                ):
                    yield event
            elif action == "character":
                async for event in self._stream_character(
                    kwargs.get("character_name"),
                    kwargs.get("genre"),
                    kwargs.get("theme")
                ):
                    yield event
            elif action == "worldview":
                async for event in self._stream_worldview(
                    kwargs.get("title"),
                    kwargs.get("theme"),
                    kwargs.get("genre")
                ):
                    yield event
            elif action == "continue":
                async for event in self._stream_continue(
                    kwargs.get("previous_content"),
                    kwargs.get("genre"),
                    kwargs.get("style"),
                    kwargs.get("word_count", 1000)
                ):
                    yield event
            else:
                yield {
                    "type": "error",
                    "error": f"不支持的操作类型: {action}",
                }
        except Exception as e:
            self.logger.error(f"小说流式生成失败: {str(e)}", exc_info=True)
            yield {
                "type": "error",
                "error": f"生成失败: {str(e)}",
            }

    async def _stream_outline(
        self,
        title: Optional[str],
        theme: Optional[str],
        genre: Optional[str],
        style: Optional[str],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()
        genre_name = self._get_genre_name(genre)
        style_name = self._get_style_name(style)
        prompt_template = self.prompt_manager.get_prompt_template(
            "tool.novel_generator_outline_prompt"
        )

        response = ""
        async for chunk in llm_manager.stream_prompt_template(
            prompt_template,
            {
                "title": title or "未命名小说",
                "genre_name": genre_name,
                "style_name": style_name,
                "theme": theme or "请围绕用户主题生成完整故事大纲",
            },
            temperature=0.8
        ):
            response += chunk
            yield {"type": "content", "content": chunk}

        yield {
            "type": "result",
            "data": {
                "title": title,
                "genre": genre_name,
                "style": style_name,
                "outline": self._parse_json_response(response, "raw_outline"),
            },
        }

    async def _stream_chapter(
        self,
        chapter_number: int,
        chapter_title: Optional[str],
        outline: Optional[str],
        genre: Optional[str],
        style: Optional[str],
        word_count: int,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()
        genre_name = self._get_genre_name(genre)
        style_name = self._get_style_name(style)
        prompt_template = self.prompt_manager.get_prompt_template(
            "tool.novel_generator_chapter_prompt"
        )

        response = ""
        async for chunk in llm_manager.stream_prompt_template(
            prompt_template,
            {
                "chapter_number": chapter_number,
                "chapter_title": chapter_title or f"第{chapter_number}章",
                "genre_name": genre_name,
                "style_name": style_name,
                "word_count": word_count,
                "outline_text": outline or "请根据上文自然展开情节",
            },
            temperature=0.8, max_tokens=word_count * 2
        ):
            response += chunk
            yield {"type": "content", "content": chunk}

        yield {
            "type": "result",
            "data": {
                "chapter_number": chapter_number,
                "chapter_title": chapter_title or f"第{chapter_number}章",
                "content": response,
                "word_count": len(response),
                "genre": genre_name,
                "style": style_name,
            },
        }

    async def _stream_character(
        self,
        character_name: Optional[str],
        genre: Optional[str],
        theme: Optional[str],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()
        genre_name = self._get_genre_name(genre)
        prompt_template = self.prompt_manager.get_prompt_template(
            "tool.novel_generator_character_prompt"
        )

        response = ""
        async for chunk in llm_manager.stream_prompt_template(
            prompt_template,
            {
                "character_name": character_name or "主角",
                "genre_name": genre_name,
                "theme": theme or "请补充完整的人物设定",
            },
            temperature=0.8
        ):
            response += chunk
            yield {"type": "content", "content": chunk}

        yield {
            "type": "result",
            "data": {
                "character": self._parse_json_response(response, "raw_character"),
                "genre": genre_name,
            },
        }

    async def _stream_worldview(
        self,
        title: Optional[str],
        theme: Optional[str],
        genre: Optional[str],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()
        genre_name = self._get_genre_name(genre)
        prompt_template = self.prompt_manager.get_prompt_template(
            "tool.novel_generator_worldview_prompt"
        )

        response = ""
        async for chunk in llm_manager.stream_prompt_template(
            prompt_template,
            {
                "title": title or "未命名小说",
                "genre_name": genre_name,
                "theme": theme or "请补充世界规则、势力与背景",
            },
            temperature=0.8
        ):
            response += chunk
            yield {"type": "content", "content": chunk}

        yield {
            "type": "result",
            "data": {
                "worldview": self._parse_json_response(response, "raw_worldview"),
                "genre": genre_name,
            },
        }

    async def _stream_continue(
        self,
        previous_content: Optional[str],
        genre: Optional[str],
        style: Optional[str],
        word_count: int,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not previous_content:
            yield {"type": "error", "error": "需要提供前文内容"}
            return

        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()
        genre_name = self._get_genre_name(genre)
        style_name = self._get_style_name(style)
        context = previous_content[-1000:] if len(previous_content) > 1000 else previous_content
        prompt_template = self.prompt_manager.get_prompt_template(
            "tool.novel_generator_continue_prompt"
        )

        response = ""
        async for chunk in llm_manager.stream_prompt_template(
            prompt_template,
            {
                "genre_name": genre_name,
                "style_name": style_name,
                "word_count": word_count,
                "context": context,
            },
            temperature=0.8, max_tokens=word_count * 2
        ):
            response += chunk
            yield {"type": "content", "content": chunk}

        yield {
            "type": "result",
            "data": {
                "continued_content": response,
                "word_count": len(response),
                "genre": genre_name,
                "style": style_name,
            },
        }

    async def _generate_outline(self, title: Optional[str], theme: Optional[str],
                               genre: Optional[str], style: Optional[str]) -> Dict[str, Any]:
        try:
            from backend.core.llm_manager import get_langchain_model_manager

            llm_manager = get_langchain_model_manager()

            genre_name = self.NOVEL_GENRES.get(genre, "未知") if genre else "未知"
            style_name = self.WRITING_STYLES.get(style, "默认") if style else "默认"

            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.novel_generator_outline_prompt"
            )

            structured_result = await llm_manager.with_structured_output(
                NovelOutlineStructuredPayload
            ).invoke_prompt_template(
                prompt_template,
                {
                    "title": title or "未命名小说",
                    "genre_name": genre_name,
                    "style_name": style_name,
                    "theme": theme or "请围绕用户主题生成完整故事大纲",
                },
                temperature=0.8,
            )
            outline_data = structured_result.model_dump(exclude_none=True)

            self.logger.info("小说大纲生成完成")
            return {
                "success": True,
                "data": {
                    "title": title,
                    "genre": genre_name,
                    "style": style_name,
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
    async def _generate_chapter(self, chapter_number: int, chapter_title: Optional[str],
                                outline: Optional[str], genre: Optional[str],
                                style: Optional[str], word_count: int) -> Dict[str, Any]:
        try:
            from backend.core.llm_manager import get_langchain_model_manager

            llm_manager = get_langchain_model_manager()

            genre_name = self.NOVEL_GENRES.get(genre, "未知") if genre else "未知"
            style_name = self.WRITING_STYLES.get(style, "默认") if style else "默认"

            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.novel_generator_chapter_prompt"
            )

            response = await llm_manager.invoke_prompt_template(
                prompt_template,
                {
                    "chapter_number": chapter_number,
                    "chapter_title": chapter_title or f"第{chapter_number}章",
                    "genre_name": genre_name,
                    "style_name": style_name,
                    "word_count": word_count,
                    "outline_text": outline or "请根据大纲自然展开剧情",
                },
                temperature=0.8,
                max_tokens=word_count * 2,
            )
            response_text = str(response or "")

            self.logger.info("章节生成完成: chapter=%s length=%s", chapter_number, len(response_text))
            return {
                "success": True,
                "data": {
                    "chapter_number": chapter_number,
                    "chapter_title": chapter_title or f"第{chapter_number}章",
                    "content": response_text,
                    "word_count": len(response_text),
                    "genre": genre_name,
                    "style": style_name,
                },
                "error": None,
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"生成章节失败: {str(e)}",
            }
    async def _generate_character(self, character_name: Optional[str],
                                  genre: Optional[str], theme: Optional[str]) -> Dict[str, Any]:
        try:
            from backend.core.llm_manager import get_langchain_model_manager

            llm_manager = get_langchain_model_manager()

            genre_name = self.NOVEL_GENRES.get(genre, "未知") if genre else "未知"

            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.novel_generator_character_prompt"
            )

            structured_result = await llm_manager.with_structured_output(
                NovelCharacterStructuredPayload
            ).invoke_prompt_template(
                prompt_template,
                {
                    "character_name": character_name or "主角",
                    "genre_name": genre_name,
                    "theme": theme or "请补充完整的人物设定",
                },
                temperature=0.8,
            )
            character_data = structured_result.model_dump(exclude_none=True)

            self.logger.info("角色设定生成完成: %s", character_name or "主角")
            return {
                "success": True,
                "data": {
                    "character": character_data,
                    "genre": genre_name,
                },
                "error": None,
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"生成角色设定失败: {str(e)}",
            }
    async def _generate_worldview(self, title: Optional[str], theme: Optional[str],
                                  genre: Optional[str]) -> Dict[str, Any]:
        try:
            from backend.core.llm_manager import get_langchain_model_manager

            llm_manager = get_langchain_model_manager()

            genre_name = self.NOVEL_GENRES.get(genre, "未知") if genre else "未知"

            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.novel_generator_worldview_prompt"
            )

            structured_result = await llm_manager.with_structured_output(
                NovelWorldviewStructuredPayload
            ).invoke_prompt_template(
                prompt_template,
                {
                    "title": title or "未命名小说",
                    "genre_name": genre_name,
                    "theme": theme or "请补充世界规则、势力与背景",
                },
                temperature=0.8,
            )
            worldview_data = structured_result.model_dump(exclude_none=True)

            self.logger.info("世界观设定生成完成")
            return {
                "success": True,
                "data": {
                    "worldview": worldview_data,
                    "genre": genre_name,
                },
                "error": None,
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"生成世界观设定失败: {str(e)}",
            }
    async def _continue_writing(self, previous_content: Optional[str],
                               genre: Optional[str], style: Optional[str],
                               word_count: int) -> Dict[str, Any]:
        try:
            if not previous_content:
                return {
                    "success": False,
                    "data": None,
                    "error": "需要提供前文内容"
                }

            from backend.core.llm_manager import get_langchain_model_manager

            llm_manager = get_langchain_model_manager()

            genre_name = self.NOVEL_GENRES.get(genre, "鏈煡") if genre else "鏈煡"
            style_name = self.WRITING_STYLES.get(style, "默认") if style else "默认"
            context = previous_content[-1000:] if len(previous_content) > 1000 else previous_content

            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.novel_generator_continue_prompt"
            )

            response = await llm_manager.invoke_prompt_template(
                prompt_template,
                {
                    "genre_name": genre_name,
                    "style_name": style_name,
                    "word_count": word_count,
                    "context": context,
                },
                temperature=0.8, max_tokens=word_count * 2,
            )

            self.logger.info(f"续写完成，字数: {len(response)}")

            return {
                "success": True,
                "data": {
                    "continued_content": response,
                    "word_count": len(response),
                    "genre": genre_name,
                    "style": style_name
                },
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"续写失败: {str(e)}"
            }

    def get_supported_genres(self) -> Dict[str, str]:
        return self.NOVEL_GENRES.copy()

    def get_supported_styles(self) -> Dict[str, str]:
        return self.WRITING_STYLES.copy()

