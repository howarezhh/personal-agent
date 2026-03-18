
from typing import Dict, Any, Optional
from backend.tools.base_tool import BaseTool, ToolDefinition, ToolParameter, ToolExecutionError
from backend.core.config_manager import get_config_manager
from backend.core.prompt_manager import get_prompt_manager
import logging
import httpx


class TranslationTool(BaseTool):
    # 支持的语言列表
    SUPPORTED_LANGUAGES = {
        "zh": "中文",
        "en": "英语",
        "ja": "日语",
        "ko": "韩语",
        "fr": "法语",
        "de": "德语",
        "es": "西班牙语",
        "ru": "俄语",
        "pt": "葡萄牙语",
        "it": "意大利语",
        "ar": "阿拉伯语",
        "th": "泰语",
        "vi": "越南语",
        "auto": "自动检测"
    }

    def __init__(self):
        super().__init__()
        self.config_manager = get_config_manager()
        self.prompt_manager = get_prompt_manager()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("翻译工具初始化完成")

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="translation",
            description="多语言翻译工具，支持中文、英语、日语、韩语、法语、德语等多种语言互译",
            category="language",
            strict_validation=True,
            parameters=[
                ToolParameter(
                    name="text",
                    type="string",
                    description="要翻译的文本内容",
                    required=True,
                    min_length=1,
                    max_length=5000,
                ),
                ToolParameter(
                    name="source_lang",
                    type="string",
                    description="源语言代码（如：zh=中文, en=英语, ja=日语, auto=自动检测）",
                    required=False,
                    default="auto",
                    enum=list(self.SUPPORTED_LANGUAGES.keys())
                ),
                ToolParameter(
                    name="target_lang",
                    type="string",
                    description="目标语言代码（如：zh=中文, en=英语, ja=日语）",
                    required=True,
                    enum=[k for k in self.SUPPORTED_LANGUAGES.keys() if k != "auto"]
                )
            ],
            timeout=30
        )

    async def execute(self, text: str, target_lang: str, source_lang: str = "auto", **kwargs) -> Dict[str, Any]:
        try:
            self.logger.info(f"开始翻译: {source_lang} -> {target_lang}, 文本长度: {len(text)}")

            # 验证语言代码
            if target_lang not in self.SUPPORTED_LANGUAGES or target_lang == "auto":
                return {
                    "success": False,
                    "data": None,
                    "error": f"不支持的目标语言: {target_lang}",
                    "error_code": "TOOL_INVALID_PARAMETER",
                    "error_type": "parameter_error",
                }

            if source_lang not in self.SUPPORTED_LANGUAGES:
                return {
                    "success": False,
                    "data": None,
                    "error": f"不支持的源语言: {source_lang}",
                    "error_code": "TOOL_INVALID_PARAMETER",
                    "error_type": "parameter_error",
                }

            # 如果源语言和目标语言相同，直接返回
            if source_lang == target_lang:
                return {
                    "success": True,
                    "data": {
                        "original_text": text,
                        "translated_text": text,
                        "source_lang": source_lang,
                        "source_lang_name": self.SUPPORTED_LANGUAGES.get(source_lang, source_lang),
                        "target_lang": target_lang,
                        "target_lang_name": self.SUPPORTED_LANGUAGES.get(target_lang, target_lang),
                        "note": "源语言和目标语言相同，无需翻译"
                    },
                    "error": None
                }

            # 使用LLM进行翻译
            translated_text = await self._translate_with_llm(text, source_lang, target_lang)

            # 检测实际的源语言（如果是自动检测）
            detected_lang = source_lang
            if source_lang == "auto":
                detected_lang = await self._detect_language(text)

            self.logger.info(f"翻译完成: {detected_lang} -> {target_lang}")

            return {
                "success": True,
                "data": {
                    "original_text": text,
                    "translated_text": translated_text,
                    "source_lang": detected_lang,
                    "source_lang_name": self.SUPPORTED_LANGUAGES.get(detected_lang, detected_lang),
                    "target_lang": target_lang,
                    "target_lang_name": self.SUPPORTED_LANGUAGES.get(target_lang, target_lang)
                },
                "error": None
            }

        except Exception as e:
            self.logger.error(f"翻译失败: {str(e)}", exc_info=True)
            raise ToolExecutionError(f"翻译失败: {str(e)}") from e

    async def _translate_with_llm(self, text: str, source_lang: str, target_lang: str) -> str:
        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()

        source_name = self.SUPPORTED_LANGUAGES.get(source_lang, source_lang)
        target_name = self.SUPPORTED_LANGUAGES.get(target_lang, target_lang)
        prompt_key = "tool.translation_auto_prompt" if source_lang == "auto" else "tool.translation_prompt"
        prompt_template = self.prompt_manager.get_prompt_template(prompt_key)

        response = await llm_manager.invoke_prompt_template(
            prompt_template,
            {
                "text": text,
                "source_name": source_name,
                "target_name": target_name,
            },
            temperature=0.3,
        )
        return response.strip()

    async def _detect_language(self, text: str) -> str:
        # 简单的语言检测逻辑
        # 检查是否包含中文字符
        if any('\u4e00' <= char <= '\u9fff' for char in text):
            return "zh"
        # 检查是否包含日文字符（平假名、片假名）
        if any('\u3040' <= char <= '\u309f' or '\u30a0' <= char <= '\u30ff' for char in text):
            return "ja"
        # 检查是否包含韩文字符
        if any('\uac00' <= char <= '\ud7af' for char in text):
            return "ko"
        # 检查是否包含阿拉伯文字符
        if any('\u0600' <= char <= '\u06ff' for char in text):
            return "ar"
        # 检查是否包含俄文字符
        if any('\u0400' <= char <= '\u04ff' for char in text):
            return "ru"
        # 检查是否包含泰文字符
        if any('\u0e00' <= char <= '\u0e7f' for char in text):
            return "th"
        # 默认为英语
        return "en"

    def get_supported_languages(self) -> Dict[str, str]:
        return self.SUPPORTED_LANGUAGES.copy()
