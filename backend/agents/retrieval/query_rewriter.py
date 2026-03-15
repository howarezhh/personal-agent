
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from backend.core.config_manager import get_config_manager
from backend.core.prompt_manager import get_prompt_manager
from backend.utils.llm_client import get_llm_client
from backend.utils.logger import get_logger


class QueryRewriter:
    def __init__(self):
        self.logger = get_logger("query_rewriter")
        self.config_manager = get_config_manager()
        self.prompt_manager = get_prompt_manager()
        self.llm_client = get_llm_client()

        retrieval_config = self.config_manager.get_agent_config("retrieval")
        self.enable_query_rewrite = retrieval_config.get("enable_query_rewrite", True)
        self.temperature = retrieval_config.get("temperature", 0.5)

    async def rewrite_query(
        self,
        query: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        if not self.enable_query_rewrite:
            return {
                "original_query": query,
                "rewritten_queries": [query],
                "keywords": [],
                "reasoning": "Query rewrite disabled",
            }

        try:
            history_str = ""
            if conversation_history:
                history_str = self.prompt_manager.format_conversation_history(
                    conversation_history,
                    prompt_type="retrieval",
                )

            prompt = self.prompt_manager.format_prompt(
                "retrieval.query_rewrite_prompt",
                question=query,
                conversation_history=history_str,
            )

            response = await self.llm_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
                max_tokens=500,
            )

            result = self._parse_rewrite_response(response, query)
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
        try:
            json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r"\{.*\}", response, re.DOTALL)
                json_str = json_match.group(0) if json_match else response

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
        candidates = rewritten_queries if isinstance(rewritten_queries, list) else [rewritten_queries]
        sanitized: List[str] = []

        original_query = (original_query or "").strip()
        if original_query:
            sanitized.append(original_query)

        for candidate in candidates:
            if not isinstance(candidate, str):
                continue

            normalized = self._normalize_query(candidate)
            if not normalized:
                continue

            if self._is_placeholder_query(normalized):
                self.logger.warning(f"Skipping placeholder rewritten query: {candidate}")
                continue

            if normalized not in sanitized:
                sanitized.append(normalized)

        return sanitized[:3] if sanitized else [original_query]

    def _normalize_query(self, query: str) -> str:
        query = (query or "").strip()
        if not query:
            return ""

        query = re.sub(r"^(?:优化|重写)查询\s*\d*\s*[:：\-]\s*", "", query)
        query = re.sub(r"\s+", " ", query)
        return query.strip()

    def _is_placeholder_query(self, query: str) -> bool:
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
        synonym_map = {
            "公司": ["企业", "组织", "机构"],
            "产品": ["商品", "服务", "项目"],
            "文档": ["文件", "资料", "材料"],
            "政策": ["规定", "制度", "条例"],
            "报告": ["报表", "总结", "汇报"],
        }

        expanded = keywords.copy()
        for keyword in keywords:
            if keyword in synonym_map:
                expanded.extend(synonym_map[keyword])

        return list(set(expanded))

    def __repr__(self) -> str:
        return f"QueryRewriter(enabled={self.enable_query_rewrite})"
