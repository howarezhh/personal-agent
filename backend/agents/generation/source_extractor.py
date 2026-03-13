"""
来源提取器
从生成的回答中提取引用来源信息
"""

import re
from typing import List, Dict, Any, Optional
from backend.utils.logger import get_logger


class SourceExtractor:
    """
    来源提取器

    功能：
    1. 从生成的内容中提取引用标记（如[1]、[2]）
    2. 匹配引用标记与检索结果
    3. 生成引用列表
    4. 验证引用的有效性
    """

    def __init__(self):
        """初始化来源提取器"""
        self.logger = get_logger(self.__class__.__name__)

        # 引用标记的正则表达式模式
        # 支持多种格式：[1]、【1】、(1)、[来源1]等
        self.citation_patterns = [
            r'\[(\d+)\]',  # [1]
            r'【(\d+)】',  # 【1】
            r'\((\d+)\)',  # (1)
            r'\[来源(\d+)\]',  # [来源1]
            r'\[参考(\d+)\]',  # [参考1]
        ]

    def extract_citations(
        self,
        content: str,
        retrieval_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        从生成的内容中提取引用信息

        Args:
            content: 生成的内容
            retrieval_results: 检索结果列表

        Returns:
            引用列表，格式为 [{"index": 1, "source_name": "xxx", "source_id": "xxx"}, ...]
        """
        if not content or not retrieval_results:
            return []

        try:
            # 提取所有引用标记
            cited_indices = self._extract_citation_indices(content)

            if not cited_indices:
                self.logger.debug("No citations found in content")
                return []

            # 构建引用列表
            citations = []
            for index in cited_indices:
                # 检查索引是否有效
                if 0 < index <= len(retrieval_results):
                    result = retrieval_results[index - 1]
                    citation = {
                        "index": index,
                        "source_name": result.get("metadata", {}).get("source", "Unknown"),
                        "source_id": result.get("id", ""),
                        "source_type": result.get("metadata", {}).get("source_type", "document"),
                        "relevance_score": result.get("score", 0.0),
                        "content_preview": result.get("content", "")[:100] + "..." if len(result.get("content", "")) > 100 else result.get("content", "")
                    }
                    citations.append(citation)
                else:
                    self.logger.warning(f"Invalid citation index: {index} (max: {len(retrieval_results)})")

            self.logger.info(f"Extracted {len(citations)} valid citations from content")
            return citations

        except Exception as e:
            self.logger.error(f"Error extracting citations: {str(e)}", exc_info=True)
            return []

    def _extract_citation_indices(self, content: str) -> List[int]:
        """
        从内容中提取所有引用索引

        Args:
            content: 内容文本

        Returns:
            引用索引列表（去重并排序）
        """
        all_indices = set()

        # 尝试所有支持的引用格式
        for pattern in self.citation_patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                try:
                    index = int(match)
                    all_indices.add(index)
                except ValueError:
                    continue

        # 排序并返回
        return sorted(list(all_indices))

    def format_citations(
        self,
        citations: List[Dict[str, Any]],
        format_type: str = "markdown"
    ) -> str:
        """
        格式化引用列表为文本

        Args:
            citations: 引用列表
            format_type: 格式类型（markdown/plain/html）

        Returns:
            格式化后的引用文本
        """
        if not citations:
            return ""

        if format_type == "markdown":
            return self._format_citations_markdown(citations)
        elif format_type == "html":
            return self._format_citations_html(citations)
        else:
            return self._format_citations_plain(citations)

    def _format_citations_markdown(self, citations: List[Dict[str, Any]]) -> str:
        """Markdown格式的引用列表"""
        lines = ["## 参考来源\n"]
        for citation in citations:
            line = f"[{citation['index']}] **{citation['source_name']}**"
            if citation.get('relevance_score'):
                line += f" (相关度: {citation['relevance_score']:.2f})"
            lines.append(line)
        return "\n".join(lines)

    def _format_citations_html(self, citations: List[Dict[str, Any]]) -> str:
        """HTML格式的引用列表"""
        lines = ['<div class="citations">', '<h3>参考来源</h3>', '<ol>']
        for citation in citations:
            line = f'<li><strong>{citation["source_name"]}</strong>'
            if citation.get('relevance_score'):
                line += f' <span class="score">(相关度: {citation["relevance_score"]:.2f})</span>'
            line += '</li>'
            lines.append(line)
        lines.extend(['</ol>', '</div>'])
        return "\n".join(lines)

    def _format_citations_plain(self, citations: List[Dict[str, Any]]) -> str:
        """纯文本格式的引用列表"""
        lines = ["参考来源："]
        for citation in citations:
            line = f"[{citation['index']}] {citation['source_name']}"
            if citation.get('relevance_score'):
                line += f" (相关度: {citation['relevance_score']:.2f})"
            lines.append(line)
        return "\n".join(lines)

    def validate_citations(
        self,
        content: str,
        citations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        验证引用的有效性

        Args:
            content: 生成的内容
            citations: 引用列表

        Returns:
            验证结果，包含统计信息
        """
        # 提取内容中的所有引用索引
        cited_indices = self._extract_citation_indices(content)

        # 统计信息
        total_citations = len(citations)
        valid_citations = len([c for c in citations if c.get('source_id')])
        citation_coverage = len(cited_indices) / total_citations if total_citations > 0 else 0

        # 检查是否有未匹配的引用
        citation_indices = {c['index'] for c in citations}
        unmatched_indices = [idx for idx in cited_indices if idx not in citation_indices]

        result = {
            "is_valid": len(unmatched_indices) == 0,
            "total_citations": total_citations,
            "valid_citations": valid_citations,
            "citation_coverage": citation_coverage,
            "unmatched_indices": unmatched_indices,
            "cited_indices": cited_indices
        }

        if unmatched_indices:
            self.logger.warning(f"Found unmatched citation indices: {unmatched_indices}")

        return result

    def add_citation_markers(
        self,
        content: str,
        retrieval_results: List[Dict[str, Any]],
        auto_cite: bool = False
    ) -> str:
        """
        为内容添加引用标记（可选功能）

        Args:
            content: 原始内容
            retrieval_results: 检索结果列表
            auto_cite: 是否自动添加引用标记

        Returns:
            添加了引用标记的内容
        """
        if not auto_cite or not retrieval_results:
            return content

        # TODO: 实现自动引用标记功能
        # 这需要更复杂的NLP技术来识别内容中哪些部分来自哪个检索结果
        self.logger.warning("Auto citation feature not implemented yet")
        return content
