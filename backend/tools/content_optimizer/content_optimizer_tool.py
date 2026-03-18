
from typing import AsyncGenerator, Dict, Any, Optional
from backend.tools.base_tool import BaseTool, ToolDefinition, ToolParameter
from backend.core.config_manager import get_config_manager
from backend.core.prompt_manager import get_prompt_manager
import logging


class ContentOptimizerTool(BaseTool):
    # 优化类型
    OPTIMIZATION_TYPES = {
        "polish": "润色",
        "rewrite": "改写",
        "expand": "扩写",
        "summarize": "缩写",
        "style_transfer": "风格转换",
        "grammar_check": "语法纠错",
        "seo_optimize": "SEO优化"
    }

    # 写作风格
    WRITING_STYLES = {
        "formal": "正式",
        "casual": "随意",
        "professional": "专业",
        "friendly": "友好",
        "persuasive": "说服性",
        "informative": "信息性",
        "creative": "创意性",
        "academic": "学术性"
    }

    def __init__(self):
        super().__init__()
        self.config_manager = get_config_manager()
        self.prompt_manager = get_prompt_manager()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("内容优化工具初始化完成")

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="content_optimizer",
            description="内容优化工具，支持文本润色、改写、扩写、缩写、风格转换、语法纠错、SEO优化等功能",
            category="utility",
            strict_validation=True,
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="操作类型：polish(润色), rewrite(改写), expand(扩写), summarize(缩写), style_transfer(风格转换), grammar_check(语法纠错), seo_optimize(SEO优化)",
                    required=True,
                    enum=list(self.OPTIMIZATION_TYPES.keys())
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description="要优化的内容",
                    required=True
                ),
                ToolParameter(
                    name="target_style",
                    type="string",
                    description="目标风格（用于风格转换）",
                    required=False,
                    enum=list(self.WRITING_STYLES.keys())
                ),
                ToolParameter(
                    name="target_length",
                    type="integer",
                    description="目标字数（用于扩写或缩写）",
                    required=False
                ),
                ToolParameter(
                    name="keywords",
                    type="string",
                    description="关键词（用于SEO优化，逗号分隔）",
                    required=False
                ),
                ToolParameter(
                    name="requirements",
                    type="string",
                    description="特殊要求或说明",
                    required=False
                )
            ],
            timeout=60
        )

    async def execute(self, action: str, content: str, **kwargs) -> Dict[str, Any]:
        try:
            self.logger.info(f"执行内容优化操作: {action}, 内容长度: {len(content)}")

            if action == "polish":
                return await self._polish_content(content, kwargs.get("requirements"))
            elif action == "rewrite":
                return await self._rewrite_content(content, kwargs.get("requirements"))
            elif action == "expand":
                return await self._expand_content(
                    content,
                    kwargs.get("target_length"),
                    kwargs.get("requirements")
                )
            elif action == "summarize":
                return await self._summarize_content(
                    content,
                    kwargs.get("target_length"),
                    kwargs.get("requirements")
                )
            elif action == "style_transfer":
                return await self._transfer_style(
                    content,
                    kwargs.get("target_style"),
                    kwargs.get("requirements")
                )
            elif action == "grammar_check":
                return await self._check_grammar(content)
            elif action == "seo_optimize":
                return await self._optimize_seo(
                    content,
                    kwargs.get("keywords"),
                    kwargs.get("requirements")
                )
            else:
                return {
                    "success": False,
                    "data": None,
                    "error": f"不支持的操作类型: {action}"
                }

        except Exception as e:
            self.logger.error(f"内容优化失败: {str(e)}", exc_info=True)
            return {
                "success": False,
                "data": None,
                "error": f"优化失败: {str(e)}"
            }

    def _get_style_name(self, style: Optional[str]) -> str:
        return self.WRITING_STYLES.get(style, "默认") if style else "默认"

    async def execute_stream(self, action: str, content: str, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
        try:
            self.logger.info(f"执行内容优化流式操作: {action}, 内容长度: {len(content)}")

            if action == "polish":
                async for event in self._stream_polish(content, kwargs.get("requirements")):
                    yield event
            elif action == "rewrite":
                async for event in self._stream_rewrite(content, kwargs.get("requirements")):
                    yield event
            elif action == "expand":
                async for event in self._stream_expand(content, kwargs.get("target_length"), kwargs.get("requirements")):
                    yield event
            elif action == "summarize":
                async for event in self._stream_summarize(content, kwargs.get("target_length"), kwargs.get("requirements")):
                    yield event
            elif action == "style_transfer":
                async for event in self._stream_style_transfer(content, kwargs.get("target_style"), kwargs.get("requirements")):
                    yield event
            elif action == "grammar_check":
                async for event in self._stream_grammar_check(content):
                    yield event
            elif action == "seo_optimize":
                async for event in self._stream_seo(content, kwargs.get("keywords"), kwargs.get("requirements")):
                    yield event
            else:
                yield {"type": "error", "error": f"不支持的操作类型: {action}"}
        except Exception as e:
            self.logger.error(f"内容优化流式处理失败: {str(e)}", exc_info=True)
            yield {"type": "error", "error": f"优化失败: {str(e)}"}

    async def _stream_polish(self, content: str, requirements: Optional[str]) -> AsyncGenerator[Dict[str, Any], None]:
        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()
        prompt_template = self.prompt_manager.get_prompt_template(
            "tool.content_optimizer_polish_prompt"
        )

        response = ""
        async for chunk in llm_manager.stream_prompt_template(
            prompt_template,
            {
                "content": content,
                "requirements": requirements or "无额外要求",
            },
            temperature=0.7
        ):
            response += chunk
            yield {"type": "content", "content": chunk}

        yield {
            "type": "result",
            "data": {
                "original_content": content,
                "optimized_content": response,
                "original_length": len(content),
                "optimized_length": len(response),
                "action": "润色",
            },
        }

    async def _stream_rewrite(self, content: str, requirements: Optional[str]) -> AsyncGenerator[Dict[str, Any], None]:
        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()
        prompt_template = self.prompt_manager.get_prompt_template(
            "tool.content_optimizer_rewrite_prompt"
        )

        response = ""
        async for chunk in llm_manager.stream_prompt_template(
            prompt_template,
            {
                "content": content,
                "requirements": requirements or "保持核心信息不变",
            },
            temperature=0.7
        ):
            response += chunk
            yield {"type": "content", "content": chunk}

        yield {
            "type": "result",
            "data": {
                "original_content": content,
                "optimized_content": response,
                "original_length": len(content),
                "optimized_length": len(response),
                "action": "改写",
            },
        }

    async def _stream_expand(
        self,
        content: str,
        target_length: Optional[int],
        requirements: Optional[str],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()
        prompt_template = self.prompt_manager.get_prompt_template(
            "tool.content_optimizer_expand_prompt"
        )

        response = ""
        async for chunk in llm_manager.stream_prompt_template(
            prompt_template,
            {
                "content": content,
                "target_length": target_length or "自动扩写",
                "requirements": requirements or "补足必要细节",
            },
            temperature=0.7
        ):
            response += chunk
            yield {"type": "content", "content": chunk}

        yield {
            "type": "result",
            "data": {
                "original_content": content,
                "optimized_content": response,
                "original_length": len(content),
                "optimized_length": len(response),
                "target_length": target_length,
                "action": "扩写",
            },
        }

    async def _stream_summarize(
        self,
        content: str,
        target_length: Optional[int],
        requirements: Optional[str],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()
        prompt_template = self.prompt_manager.get_prompt_template(
            "tool.content_optimizer_summarize_prompt"
        )

        response = ""
        async for chunk in llm_manager.stream_prompt_template(
            prompt_template,
            {
                "content": content,
                "target_length": target_length or "自动摘要",
                "requirements": requirements or "保留关键信息",
            },
            temperature=0.5
        ):
            response += chunk
            yield {"type": "content", "content": chunk}

        yield {
            "type": "result",
            "data": {
                "original_content": content,
                "optimized_content": response,
                "original_length": len(content),
                "optimized_length": len(response),
                "target_length": target_length,
                "compression_ratio": f"{len(response) / len(content) * 100:.1f}%" if content else "0.0%",
                "action": "缩写",
            },
        }

    async def _stream_style_transfer(
        self,
        content: str,
        target_style: Optional[str],
        requirements: Optional[str],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()
        style_name = self._get_style_name(target_style)
        prompt_template = self.prompt_manager.get_prompt_template(
            "tool.content_optimizer_style_transfer_prompt"
        )

        response = ""
        async for chunk in llm_manager.stream_prompt_template(
            prompt_template,
            {
                "content": content,
                "style_name": style_name,
                "requirements": requirements or "保持原意不变",
            },
            temperature=0.7
        ):
            response += chunk
            yield {"type": "content", "content": chunk}

        yield {
            "type": "result",
            "data": {
                "original_content": content,
                "optimized_content": response,
                "original_length": len(content),
                "optimized_length": len(response),
                "target_style": style_name,
                "action": "风格转换",
            },
        }

    async def _stream_grammar_check(self, content: str) -> AsyncGenerator[Dict[str, Any], None]:
        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()
        prompt_template = self.prompt_manager.get_prompt_template(
            "tool.content_optimizer_grammar_check_prompt"
        )

        response = ""
        async for chunk in llm_manager.stream_prompt_template(
            prompt_template,
            {
                "content": content,
            },
            temperature=0.3
        ):
            response += chunk
            yield {"type": "content", "content": chunk}

        yield {
            "type": "result",
            "data": {
                "original_content": content,
                "check_result": response,
                "action": "语法纠错",
            },
        }

    async def _stream_seo(
        self,
        content: str,
        keywords: Optional[str],
        requirements: Optional[str],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from backend.core.llm_manager import get_langchain_model_manager

        llm_manager = get_langchain_model_manager()
        prompt_template = self.prompt_manager.get_prompt_template(
            "tool.content_optimizer_seo_prompt"
        )

        response = ""
        async for chunk in llm_manager.stream_prompt_template(
            prompt_template,
            {
                "content": content,
                "keywords": keywords or "无关键词",
                "requirements": requirements or "提升搜索友好度",
            },
            temperature=0.7
        ):
            response += chunk
            yield {"type": "content", "content": chunk}

        yield {
            "type": "result",
            "data": {
                "original_content": content,
                "optimized_content": response,
                "original_length": len(content),
                "optimized_length": len(response),
                "keywords": keywords,
                "action": "SEO优化",
            },
        }

    async def _polish_content(self, content: str, requirements: Optional[str]) -> Dict[str, Any]:
        try:
            from backend.core.llm_manager import get_langchain_model_manager

            llm_manager = get_langchain_model_manager()

            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.content_optimizer_polish_prompt"
            )

            response = await llm_manager.invoke_prompt_template(
                prompt_template,
                {
                    "content": content,
                    "requirements": requirements or "无额外要求",
                },
                temperature=0.7,
            )

            self.logger.info(f"内容润色完成，原文长度: {len(content)}, 润色后长度: {len(response)}")

            return {
                "success": True,
                "data": {
                    "original_content": content,
                    "optimized_content": response,
                    "original_length": len(content),
                    "optimized_length": len(response),
                    "action": "润色"
                },
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"润色失败: {str(e)}"
            }

    async def _rewrite_content(self, content: str, requirements: Optional[str]) -> Dict[str, Any]:
        try:
            from backend.core.llm_manager import get_langchain_model_manager

            llm_manager = get_langchain_model_manager()

            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.content_optimizer_rewrite_prompt"
            )

            response = await llm_manager.invoke_prompt_template(
                prompt_template,
                {
                    "content": content,
                    "requirements": requirements or "保持核心信息不变",
                },
                temperature=0.8,
            )

            self.logger.info(f"内容改写完成，原文长度: {len(content)}, 改写后长度: {len(response)}")

            return {
                "success": True,
                "data": {
                    "original_content": content,
                    "optimized_content": response,
                    "original_length": len(content),
                    "optimized_length": len(response),
                    "action": "改写"
                },
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"改写失败: {str(e)}"
            }

    async def _expand_content(self, content: str, target_length: Optional[int],
                             requirements: Optional[str]) -> Dict[str, Any]:
        try:
            from backend.core.llm_manager import get_langchain_model_manager

            llm_manager = get_langchain_model_manager()

            max_tokens = target_length * 2 if target_length else 3000
            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.content_optimizer_expand_prompt"
            )
            response = await llm_manager.invoke_prompt_template(
                prompt_template,
                {
                    "content": content,
                    "target_length": target_length or "自动扩写",
                    "requirements": requirements or "补足必要细节",
                },
                temperature=0.7, max_tokens=max_tokens,
            )

            self.logger.info(f"内容扩写完成，原文长度: {len(content)}, 扩写后长度: {len(response)}")

            return {
                "success": True,
                "data": {
                    "original_content": content,
                    "optimized_content": response,
                    "original_length": len(content),
                    "optimized_length": len(response),
                    "target_length": target_length,
                    "action": "扩写"
                },
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"扩写失败: {str(e)}"
            }

    async def _summarize_content(self, content: str, target_length: Optional[int],
                                requirements: Optional[str]) -> Dict[str, Any]:
        try:
            from backend.core.llm_manager import get_langchain_model_manager

            llm_manager = get_langchain_model_manager()

            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.content_optimizer_summarize_prompt"
            )

            response = await llm_manager.invoke_prompt_template(
                prompt_template,
                {
                    "content": content,
                    "target_length": target_length or "自动摘要",
                    "requirements": requirements or "保留关键信息",
                },
                temperature=0.5,
            )

            self.logger.info(f"内容缩写完成，原文长度: {len(content)}, 缩写后长度: {len(response)}")

            return {
                "success": True,
                "data": {
                    "original_content": content,
                    "optimized_content": response,
                    "original_length": len(content),
                    "optimized_length": len(response),
                    "target_length": target_length,
                    "compression_ratio": f"{len(response) / len(content) * 100:.1f}%",
                    "action": "缩写"
                },
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"缩写失败: {str(e)}"
            }

    async def _transfer_style(self, content: str, target_style: Optional[str],
                             requirements: Optional[str]) -> Dict[str, Any]:
        try:
            from backend.core.llm_manager import get_langchain_model_manager

            llm_manager = get_langchain_model_manager()

            style_name = self.WRITING_STYLES.get(target_style, "默认") if target_style else "默认"
            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.content_optimizer_style_transfer_prompt"
            )

            response = await llm_manager.invoke_prompt_template(
                prompt_template,
                {
                    "content": content,
                    "style_name": style_name,
                    "requirements": requirements or "保持原意不变",
                },
                temperature=0.7,
            )

            self.logger.info(f"风格转换完成，目标风格: {style_name}")

            return {
                "success": True,
                "data": {
                    "original_content": content,
                    "optimized_content": response,
                    "original_length": len(content),
                    "optimized_length": len(response),
                    "target_style": style_name,
                    "action": "风格转换"
                },
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"风格转换失败: {str(e)}"
            }

    async def _check_grammar(self, content: str) -> Dict[str, Any]:
        try:
            from backend.core.llm_manager import get_langchain_model_manager

            llm_manager = get_langchain_model_manager()

            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.content_optimizer_grammar_check_prompt"
            )

            response = await llm_manager.invoke_prompt_template(
                prompt_template,
                {
                    "content": content,
                },
                temperature=0.3,
            )

            self.logger.info("语法检查完成")

            return {
                "success": True,
                "data": {
                    "original_content": content,
                    "check_result": response,
                    "action": "语法纠错"
                },
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"语法检查失败: {str(e)}"
            }

    async def _optimize_seo(self, content: str, keywords: Optional[str],
                           requirements: Optional[str]) -> Dict[str, Any]:
        try:
            from backend.core.llm_manager import get_langchain_model_manager

            llm_manager = get_langchain_model_manager()

            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.content_optimizer_seo_prompt"
            )

            response = await llm_manager.invoke_prompt_template(
                prompt_template,
                {
                    "content": content,
                    "keywords": keywords or "无关键词",
                    "requirements": requirements or "提升搜索友好度",
                },
                temperature=0.7,
            )

            self.logger.info("SEO优化完成")

            return {
                "success": True,
                "data": {
                    "original_content": content,
                    "optimized_content": response,
                    "original_length": len(content),
                    "optimized_length": len(response),
                    "keywords": keywords,
                    "action": "SEO优化"
                },
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"SEO优化失败: {str(e)}"
            }

    def get_supported_optimizations(self) -> Dict[str, str]:
        return self.OPTIMIZATION_TYPES.copy()

    def get_supported_styles(self) -> Dict[str, str]:
        return self.WRITING_STYLES.copy()
