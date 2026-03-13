"""
小说生成工具
支持AI自动生成小说内容
"""

from typing import Dict, Any, Optional, List
from backend.tools.base_tool import BaseTool, ToolDefinition, ToolParameter
from backend.core.config_manager import get_config_manager
from backend.core.prompt_manager import get_prompt_manager
import logging
import json


class NovelGeneratorTool(BaseTool):
    """
    小说生成工具

    功能：
    - 生成小说大纲
    - 生成章节内容
    - 生成角色设定
    - 生成世界观设定
    - 续写小说内容
    """

    # 小说类型
    NOVEL_GENRES = {
        "fantasy": "玄幻",
        "urban": "都市",
        "romance": "言情",
        "scifi": "科幻",
        "wuxia": "武侠",
        "xianxia": "仙侠",
        "history": "历史",
        "military": "军事",
        "mystery": "悬疑",
        "horror": "恐怖",
        "game": "游戏",
        "sports": "体育",
        "fanfic": "同人"
    }

    # 写作风格
    WRITING_STYLES = {
        "descriptive": "描写细腻",
        "concise": "简洁明快",
        "humorous": "幽默风趣",
        "serious": "严肃正经",
        "poetic": "诗意优美",
        "suspenseful": "悬念迭起"
    }

    def __init__(self):
        """初始化小说生成工具"""
        super().__init__()
        self.config_manager = get_config_manager()
        self.prompt_manager = get_prompt_manager()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("小说生成工具初始化完成")

    def _create_definition(self) -> ToolDefinition:
        """创建工具定义"""
        return ToolDefinition(
            name="novel_generator",
            description="AI小说生成工具，支持生成小说大纲、章节内容、角色设定、世界观设定等",
            category="creative",
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="操作类型：outline(生成大纲), chapter(生成章节), character(生成角色), worldview(生成世界观), continue(续写)",
                    required=True,
                    enum=["outline", "chapter", "character", "worldview", "continue"]
                ),
                ToolParameter(
                    name="genre",
                    type="string",
                    description="小说类型",
                    required=False,
                    enum=list(self.NOVEL_GENRES.keys())
                ),
                ToolParameter(
                    name="style",
                    type="string",
                    description="写作风格",
                    required=False,
                    enum=list(self.WRITING_STYLES.keys())
                ),
                ToolParameter(
                    name="title",
                    type="string",
                    description="小说标题",
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
                    description="章节编号",
                    required=False
                ),
                ToolParameter(
                    name="chapter_title",
                    type="string",
                    description="章节标题",
                    required=False
                ),
                ToolParameter(
                    name="previous_content",
                    type="string",
                    description="前文内容（用于续写）",
                    required=False
                ),
                ToolParameter(
                    name="character_name",
                    type="string",
                    description="角色名称",
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
                    description="小说大纲（用于生成章节）",
                    required=False
                )
            ],
            timeout=120
        )

    async def execute(self, action: str, **kwargs) -> Dict[str, Any]:
        """
        执行小说生成操作

        Args:
            action: 操作类型
            **kwargs: 其他参数

        Returns:
            生成结果
        """
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

    async def _generate_outline(self, title: Optional[str], theme: Optional[str],
                               genre: Optional[str], style: Optional[str]) -> Dict[str, Any]:
        """生成小说大纲"""
        try:
            from backend.core.llm_manager import get_llm_manager

            llm_manager = get_llm_manager()

            genre_name = self.NOVEL_GENRES.get(genre, "??") if genre else "??"
            style_name = self.WRITING_STYLES.get(style, "????") if style else "????"

            prompt = self.prompt_manager.format_prompt(
                "tool.novel_generator_outline_prompt",
                title=title or "??",
                genre_name=genre_name,
                style_name=style_name,
                theme=theme or "????????????"
            )

            response = await llm_manager.generate(prompt, temperature=0.8)

            # 尝试解析JSON
            try:
                # 提取JSON部分
                json_start = response.find('{')
                json_end = response.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = response[json_start:json_end]
                    outline_data = json.loads(json_str)
                else:
                    # 如果没有JSON格式，返回原始文本
                    outline_data = {"raw_outline": response}
            except:
                outline_data = {"raw_outline": response}

            self.logger.info("小说大纲生成完成")

            return {
                "success": True,
                "data": {
                    "title": title,
                    "genre": genre_name,
                    "style": style_name,
                    "outline": outline_data
                },
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"生成大纲失败: {str(e)}"
            }

    async def _generate_chapter(self, chapter_number: int, chapter_title: Optional[str],
                                outline: Optional[str], genre: Optional[str],
                                style: Optional[str], word_count: int) -> Dict[str, Any]:
        """生成章节内容"""
        try:
            from backend.core.llm_manager import get_llm_manager

            llm_manager = get_llm_manager()

            genre_name = self.NOVEL_GENRES.get(genre, "??") if genre else "??"
            style_name = self.WRITING_STYLES.get(style, "????") if style else "????"

            prompt = self.prompt_manager.format_prompt(
                "tool.novel_generator_chapter_prompt",
                chapter_number=chapter_number,
                chapter_title=chapter_title or f"?{chapter_number}?",
                genre_name=genre_name,
                style_name=style_name,
                word_count=word_count,
                outline_text=outline or "?"
            )

            response = await llm_manager.generate(prompt, temperature=0.8, max_tokens=word_count * 2)

            self.logger.info(f"第{chapter_number}章生成完成，字数: {len(response)}")

            return {
                "success": True,
                "data": {
                    "chapter_number": chapter_number,
                    "chapter_title": chapter_title or f"第{chapter_number}章",
                    "content": response,
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
                "error": f"生成章节失败: {str(e)}"
            }

    async def _generate_character(self, character_name: Optional[str],
                                  genre: Optional[str], theme: Optional[str]) -> Dict[str, Any]:
        """生成角色设定"""
        try:
            from backend.core.llm_manager import get_llm_manager

            llm_manager = get_llm_manager()

            genre_name = self.NOVEL_GENRES.get(genre, "??") if genre else "??"

            prompt = self.prompt_manager.format_prompt(
                "tool.novel_generator_character_prompt",
                character_name=character_name or "??",
                genre_name=genre_name,
                theme=theme or "?????"
            )

            response = await llm_manager.generate(prompt, temperature=0.8)

            # 尝试解析JSON
            try:
                json_start = response.find('{')
                json_end = response.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = response[json_start:json_end]
                    character_data = json.loads(json_str)
                else:
                    character_data = {"raw_character": response}
            except:
                character_data = {"raw_character": response}

            self.logger.info(f"角色设定生成完成: {character_name}")

            return {
                "success": True,
                "data": {
                    "character": character_data,
                    "genre": genre_name
                },
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"生成角色设定失败: {str(e)}"
            }

    async def _generate_worldview(self, title: Optional[str], theme: Optional[str],
                                  genre: Optional[str]) -> Dict[str, Any]:
        """生成世界观设定"""
        try:
            from backend.core.llm_manager import get_llm_manager

            llm_manager = get_llm_manager()

            genre_name = self.NOVEL_GENRES.get(genre, "??") if genre else "??"

            prompt = self.prompt_manager.format_prompt(
                "tool.novel_generator_worldview_prompt",
                title=title or "??",
                genre_name=genre_name,
                theme=theme or "?????"
            )

            response = await llm_manager.generate(prompt, temperature=0.8)

            # 尝试解析JSON
            try:
                json_start = response.find('{')
                json_end = response.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = response[json_start:json_end]
                    worldview_data = json.loads(json_str)
                else:
                    worldview_data = {"raw_worldview": response}
            except:
                worldview_data = {"raw_worldview": response}

            self.logger.info("世界观设定生成完成")

            return {
                "success": True,
                "data": {
                    "worldview": worldview_data,
                    "genre": genre_name
                },
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"生成世界观设定失败: {str(e)}"
            }

    async def _continue_writing(self, previous_content: Optional[str],
                               genre: Optional[str], style: Optional[str],
                               word_count: int) -> Dict[str, Any]:
        """续写小说内容"""
        try:
            if not previous_content:
                return {
                    "success": False,
                    "data": None,
                    "error": "需要提供前文内容"
                }

            from backend.core.llm_manager import get_llm_manager

            llm_manager = get_llm_manager()

            genre_name = self.NOVEL_GENRES.get(genre, "??") if genre else "??"
            style_name = self.WRITING_STYLES.get(style, "????") if style else "????"
            context = previous_content[-1000:] if len(previous_content) > 1000 else previous_content

            prompt = self.prompt_manager.format_prompt(
                "tool.novel_generator_continue_prompt",
                genre_name=genre_name,
                style_name=style_name,
                word_count=word_count,
                context=context
            )

            response = await llm_manager.generate(prompt, temperature=0.8, max_tokens=word_count * 2)

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
        """获取支持的小说类型"""
        return self.NOVEL_GENRES.copy()

    def get_supported_styles(self) -> Dict[str, str]:
        """获取支持的写作风格"""
        return self.WRITING_STYLES.copy()
