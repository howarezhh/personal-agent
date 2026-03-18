# -*- coding: utf-8 -*-

from __future__ import annotations

"""
查询改写模块。

本模块的目标是把用户原始问题改写成更适合检索系统处理的查询集合。
它会综合以下信息：

1. 用户当前问题本身。
2. 多轮对话历史上下文。
3. Prompt 模板中定义的输出格式约束。
4. LLM 返回的结构化改写结果。

为了降低模型输出不稳定带来的风险，模块内部还会做 JSON 解析、占位语句过滤、
重复查询去重和兜底回退，保证外部调用方始终拿到可用的查询列表。
"""

import json
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.core.config_manager import get_config_manager
from backend.core.prompt_manager import get_prompt_manager
from backend.core.llm_manager import get_langchain_model_manager
from backend.utils.logger import get_logger


class QueryRewriteStructuredResult(BaseModel):
    """Query rewriter."""

    rewritten_queries: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    reasoning: str = ""


class QueryRewriter:
    """查询改写器。

    负责根据原始问题、多轮上下文和 Prompt 模板，
    生成更适合检索的改写查询、关键词和补充表达。
    """

    def __init__(self):
        """初始化查询改写所需的依赖与配置。"""
        # `self.logger`：记录查询改写过程中的信息、告警和错误。
        self.logger = get_logger("query_rewriter")
        # `self.config_manager`：统一读取检索 Agent 相关配置。
        self.config_manager = get_config_manager()
        # `self.prompt_manager`：负责格式化查询改写 Prompt 和对话历史。
        self.prompt_manager = get_prompt_manager()
        # `self.llm_client`：负责向模型发送改写请求并获取响应。
        self.model_manager = get_langchain_model_manager()

        # `retrieval_config`：检索模块的集中配置字典。
        retrieval_config = self.config_manager.get_agent_config("retrieval")
        # `self.enable_query_rewrite`：是否启用查询改写流程。
        self.enable_query_rewrite = retrieval_config.get("enable_query_rewrite", True)
        # `self.temperature`：查询改写时使用的模型温度参数。
        self.temperature = retrieval_config.get("temperature", 0.5)

    async def rewrite_query(
        self,
        query: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """执行查询改写流程并返回结构化结果。

        返回字典中至少保证包含：
        - `original_query`：原始查询。
        - `rewritten_queries`：可直接用于检索的查询列表。
        - `keywords`：从结果中提取出的关键词列表。
        - `reasoning`：本次改写的简单说明或失败原因。
        """
        if not self.enable_query_rewrite:
            return {
                "original_query": query,
                "rewritten_queries": [query],
                "keywords": [],
                "reasoning": "Query rewrite disabled",
            }

        try:
            # `history_str`：格式化后的多轮对话历史，供 Prompt 使用。
            history_str = ""
            if conversation_history:
                history_str = self.prompt_manager.format_conversation_history(
                    conversation_history,
                    prompt_type="retrieval",
                )

            # `prompt_template`: standardized rewrite prompt from PromptManager.
            prompt_template = self.prompt_manager.get_prompt_template(
                "retrieval.query_rewrite_prompt"
            )

            # `structured_result`: structured model output validated by the declared schema.
            structured_result = await self.model_manager.with_structured_output(
                QueryRewriteStructuredResult
            ).invoke_prompt_template(
                prompt_template,
                {
                    "question": query,
                    "conversation_history": history_str,
                },
                temperature=self.temperature,
                max_tokens=500,
            )

            # Fall back to the original query if rewriting fails.
            result = {
                "original_query": query,
                "rewritten_queries": self._sanitize_rewritten_queries(query, structured_result.rewritten_queries),
                "keywords": structured_result.keywords or self.extract_keywords(query),
                "reasoning": structured_result.reasoning or "LLM structured rewrite",
            }
            self.logger.info(
                f"Query rewritten: '{query}' -> {len(result['rewritten_queries'])} queries"
            )
            return result
        except Exception as exc:
            self.logger.error(f"Failed to rewrite query: {exc}")
            return {
                "original_query": query,
                "rewritten_queries": [query],
                "keywords": [],
                "reasoning": f"Rewrite failed: {exc}",
            }

    def _parse_rewrite_response(self, response: str, original_query: str) -> Dict[str, Any]:
        """解析模型返回内容，尽量提取稳定的改写结果。

        解析策略分三级：
        1. 优先提取 ```json``` 代码块中的内容。
        2. 其次尝试提取普通文本里的 JSON 对象片段。
        3. 最后把完整响应交给 JSON 解析，并在失败时回退原始查询。
        """
        try:
            json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r"\{.*\}", response, re.DOTALL)
                json_str = json_match.group(0) if json_match else response

            # `result`：反序列化后的模型结构化输出。
            result = json.loads(json_str)
            result.setdefault("original_query", original_query)
            result.setdefault("keywords", [])
            result.setdefault("reasoning", "No reasoning provided")
            result["rewritten_queries"] = self._sanitize_rewritten_queries(
                original_query=original_query,
                rewritten_queries=result.get("rewritten_queries", []),
            )
            return result
        except json.JSONDecodeError as exc:
            self.logger.warning(f"Failed to parse rewrite JSON: {exc}; fallback to original query")
            return {
                "original_query": original_query,
                "rewritten_queries": [original_query],
                "keywords": [],
                "reasoning": "JSON parse failed",
            }
        except Exception as exc:
            self.logger.error(f"Failed to parse rewrite response: {exc}")
            return {
                "original_query": original_query,
                "rewritten_queries": [original_query],
                "keywords": [],
                "reasoning": f"Parse failed: {exc}",
            }

    def _sanitize_rewritten_queries(self, original_query: str, rewritten_queries: Any) -> List[str]:
        """清洗改写查询，去除空值、模板语句和重复项。"""
        # `candidates`：统一把单个值和列表值都转换成可遍历候选集合。
        candidates = rewritten_queries if isinstance(rewritten_queries, list) else [rewritten_queries]
        # `sanitized`：最终保留的查询列表，默认优先保留原始查询。
        sanitized: List[str] = []

        original_query = (original_query or "").strip()
        if original_query:
            sanitized.append(original_query)

        for candidate in candidates:
            if not isinstance(candidate, str):
                continue

            # `normalized`：去除模板前缀和多余空白后的查询文本。
            normalized = self._normalize_query(candidate)
            if not normalized:
                continue

            # 过滤掉“优化查询 1”“核心意图”等非真实查询文本。
            if self._is_placeholder_query(normalized):
                self.logger.warning(f"Skipping placeholder rewritten query: {candidate}")
                continue

            if normalized not in sanitized:
                sanitized.append(normalized)

        # 限制最大查询数，避免后续检索阶段因改写过多而过度放大成本。
        return sanitized[:3] if sanitized else [original_query]

    def _normalize_query(self, query: str) -> str:
        """对查询文本做归一化处理。"""
        query = (query or "").strip()
        if not query:
            return ""

        # 去掉模型经常输出的“优化查询 1:”“重写查询：”等模板前缀。
        query = re.sub(r"^(?:优化|重写)查询\s*\d*\s*[:：\-]\s*", "", query)
        query = re.sub(r"\s+", " ", query)
        return query.strip()

    def _is_placeholder_query(self, query: str) -> bool:
        """判断改写结果是否仍是占位文本或无效表达。"""
        # `placeholder_patterns`：匹配明显不是查询内容的模板句式。
        placeholder_patterns = [
            r"^(?:优化|重写)查询\s*\d*$",
            r"^基于核心意图(?:和扩展术语)?$",
            r"^结合同义(?:词|和相关概念)?$",
            r"^扩展术语$",
            r"^相关概念$",
            r"^核心意图$",
        ]
        if any(re.match(pattern, query) for pattern in placeholder_patterns):
            return True

        # `generic_markers`：对短小泛化表达做补充过滤。
        generic_markers = [
            "优化查询",
            "重写查询",
            "基于核心意图",
            "扩展术语",
            "同义",
            "相关概念",
        ]
        return any(marker in query for marker in generic_markers) and len(query) <= 24

    def extract_keywords(self, query: str) -> List[str]:
        """从查询中提取核心关键词。

        这是一个轻量规则实现，主要用于在模型不可用时补充基础关键词能力。
        """
        cleaned = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", query)
        words = cleaned.split()
        stopwords = {
            "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都",
            "一个", "也", "很", "到", "说", "要", "去", "你", "会", "着",
            "没有", "看", "好", "自己", "这",
        }
        keywords = [word for word in words if word and word not in stopwords and len(word) > 1]
        return keywords[:10]

    def expand_synonyms(self, keywords: List[str]) -> List[str]:
        """对关键词做轻量同义扩展。"""
        synonym_map = {
            "公司": ["企业", "组织", "机构"],
            "产品": ["商品", "服务", "项目"],
            "文档": ["文件", "资料", "材料"],
            "政策": ["规定", "制度", "条例"],
            "报告": ["报表", "总结", "汇报"],
        }

        # `expanded`：在原始关键词基础上叠加同义词后的列表。
        expanded = keywords.copy()
        for keyword in keywords:
            if keyword in synonym_map:
                expanded.extend(synonym_map[keyword])

        # 使用集合去重，避免同义词扩展后重复参与检索。
        return list(set(expanded))

    def __repr__(self) -> str:
        """返回查询改写器的调试表示。"""
        return f"QueryRewriter(enabled={self.enable_query_rewrite})"
