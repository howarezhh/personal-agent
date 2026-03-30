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

import re
import unicodedata
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.core.config_manager import get_config_manager
from backend.core.prompt_manager import get_prompt_manager
from backend.core.llm_manager import get_langchain_model_manager
from backend.utils.logger import get_logger


class QueryRewriteStructuredResult(BaseModel):
    """Query rewriter."""

    rewritten_queries: List[str] = Field(default_factory=list)
    decomposed_queries: List[str] = Field(default_factory=list)
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
        retrieval_context: Optional[Dict[str, Any]] = None,
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
            # 统一走 ChatPromptTemplate，避免先把历史拼成大字符串再交给模型。
            # `normalized_context`：把检索上下文压缩为 Prompt 可稳定消费的短文本。
            normalized_context = self._format_retrieval_context(retrieval_context)
            prompt_template, prompt_variables = self.prompt_manager.build_chat_prompt_call(
                user_prompt_key="retrieval.query_rewrite_prompt",
                user_variables={
                    "question": query,
                    "file_type_hint": normalized_context.get("file_type_hint", "未指定"),
                    "retrieval_context": normalized_context.get("retrieval_context", "无额外检索上下文"),
                },
                conversation_history=conversation_history,
            )

            # `structured_result`: structured model output validated by the declared schema.
            structured_result = await self.model_manager.with_structured_output(
                QueryRewriteStructuredResult
            ).invoke_chat_prompt_template(
                prompt_template,
                prompt_variables,
                temperature=self.temperature,
                max_tokens=500,
            )

            # Fall back to the original query if rewriting fails.
            result = {
                "original_query": query,
                "rewritten_queries": self._sanitize_rewritten_queries(query, structured_result.rewritten_queries),
                "decomposed_queries": self._sanitize_rewritten_queries(query, structured_result.decomposed_queries),
                "keywords": structured_result.keywords or self.extract_keywords(query),
                "reasoning": structured_result.reasoning or "LLM structured rewrite",
                "rewrite_applied": True,
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
                "decomposed_queries": [query],
                "keywords": self.extract_keywords(query),
                "reasoning": f"Rewrite failed: {exc}",
                "rewrite_applied": False,
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
        normalized_query = unicodedata.normalize("NFKC", str(query or "")).lower()
        exact_phrases = self._extract_exact_phrases(normalized_query)
        segments = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", normalized_query)
        stopwords = {
            "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都",
            "一个", "也", "很", "到", "说", "要", "去", "你", "会", "着",
            "没有", "看", "好", "自己", "这",
        }
        keywords: List[str] = []

        # 中文说明：优先保留用户明确用引号指定的短语，对标题、列名、键名类查询更稳定。
        for phrase in exact_phrases:
            if phrase not in keywords:
                keywords.append(phrase)

        for segment in segments:
            if re.fullmatch(r"[a-z0-9]+", segment):
                if len(segment) > 1 and segment not in stopwords and segment not in keywords:
                    keywords.append(segment)
                continue

            if len(segment) <= 2:
                if segment not in stopwords and segment not in keywords:
                    keywords.append(segment)
                continue

            if len(segment) <= 8 and segment not in stopwords and segment not in keywords:
                keywords.append(segment)

            for token_length in (4, 3, 2):
                if len(segment) < token_length:
                    continue
                for start_index in range(0, len(segment) - token_length + 1):
                    token = segment[start_index:start_index + token_length]
                    if token in stopwords or token in keywords:
                        continue
                    keywords.append(token)
                    if len(keywords) >= 10:
                        return keywords[:10]

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

        # 中文说明：这里不能直接 `set()` 去重，否则会打乱关键词顺序，
        # 从而导致 query plan 在不同进程/不同运行中出现抖动。
        deduplicated: List[str] = []
        for keyword in expanded:
            if keyword not in deduplicated:
                deduplicated.append(keyword)
        return deduplicated

    @staticmethod
    def _extract_exact_phrases(query: str) -> List[str]:
        """提取查询中的精确短语，供关键词兜底提取优先保留。"""
        if not query:
            return []

        phrases: List[str] = []
        for pattern in (r'["“](.{2,}?)[”"]', r"[《「](.{2,}?)[》」]"):
            for match in re.findall(pattern, query):
                candidate = str(match or "").strip()
                if candidate and candidate not in phrases:
                    phrases.append(candidate)
        return phrases

    @staticmethod
    def _format_retrieval_context(retrieval_context: Optional[Dict[str, Any]]) -> Dict[str, str]:
        """把检索上下文压缩成稳定、简短的 Prompt 变量。"""
        if not isinstance(retrieval_context, dict):
            return {
                "file_type_hint": "未指定",
                "retrieval_context": "无额外检索上下文",
            }

        file_type = str(retrieval_context.get("file_type") or "").strip() or "未指定"
        knowledge_base_id = str(retrieval_context.get("knowledge_base_id") or "").strip()
        filter_summary = retrieval_context.get("vector_search_filter")
        filter_text = ""
        if isinstance(filter_summary, dict) and filter_summary:
            filter_pairs = [f"{key}={value}" for key, value in filter_summary.items() if value is not None]
            filter_text = ", ".join(filter_pairs)

        context_parts = [f"目标文档类型: {file_type}"]
        if knowledge_base_id:
            context_parts.append(f"知识库: {knowledge_base_id}")
        if filter_text:
            context_parts.append(f"过滤条件: {filter_text}")
        return {
            "file_type_hint": file_type,
            "retrieval_context": "；".join(context_parts),
        }

    def __repr__(self) -> str:
        """返回查询改写器的调试表示。"""
        return f"QueryRewriter(enabled={self.enable_query_rewrite})"
