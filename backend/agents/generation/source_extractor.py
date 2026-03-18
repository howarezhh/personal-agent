# -*- coding: utf-8 -*-


from __future__ import annotations
"""
引用提取模块，负责从生成回答中提取引用标记，格式化参考来源并校验引用完整性。
"""


import re
from typing import Any, Dict, List

from backend.utils.citation_utils import resolve_source_name
from backend.utils.logger import get_logger


class SourceExtractor:
    """
    引用提取器，用于解析回答中的引用编号并将其映射为可读的来源信息。
    """
    def __init__(self):
        """
        初始化引用提取器，准备引用匹配模式和日志对象。
        """
        self.logger = get_logger(self.__class__.__name__)
        # 同时支持多种常见的引用标记写法，便于兼容不同 Prompt 或模型输出风格。
        self.citation_patterns = [
            r'\[(\d+)\]',
            r'【(\d+)】',
            r'\((\d+)\)',
            r'\[来源(\d+)\]',
            r'【来源(\d+)】',
            r'\[参考(\d+)\]',
            r'【参考(\d+)】',
        ]

    def extract_citations(
        self,
        content: str,
        retrieval_results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        从回答内容中提取引用编号，并根据检索结果构建来源列表。
        """
        if not content or not retrieval_results:
            return []

        try:
            cited_indices = self._extract_citation_indices(content)
            if not cited_indices:
                self.logger.debug('No citations found in content')
                return []

            citations: List[Dict[str, Any]] = []
            for index in cited_indices:
                if 0 < index <= len(retrieval_results):
                    result = retrieval_results[index - 1]
                    metadata = result.get('metadata', {}) if isinstance(result.get('metadata'), dict) else {}
                    content_text = result.get('content', '') or ''
                    # 将引用编号转换为结构化来源对象，便于后续展示和校验。
                    citations.append(
                        {
                            'index': index,
                            'source_name': resolve_source_name({**metadata, **result}, default='Unknown'),
                            'source_id': result.get('id', ''),
                            'source_type': metadata.get('source_type', 'document'),
                            'relevance_score': result.get('score', 0.0),
                            'content_preview': content_text[:100] + '...' if len(content_text) > 100 else content_text,
                        }
                    )
                else:
                    self.logger.warning('Invalid citation index: %s (max: %s)', index, len(retrieval_results))

            self.logger.info('Extracted %s valid citations from content', len(citations))
            return citations
        except Exception as exc:
            self.logger.error('Error extracting citations: %s', str(exc), exc_info=True)
            return []

    def _extract_citation_indices(self, content: str) -> List[int]:
        """
        使用预定义的正则模式提取内容中的所有引用编号。
        """
        all_indices: set[int] = set()
        for pattern in self.citation_patterns:
            for match in re.findall(pattern, content):
                try:
                    all_indices.add(int(match))
                except (TypeError, ValueError):
                    continue
        return sorted(all_indices)

    def format_citations(self, citations: List[Dict[str, Any]], format_type: str = 'markdown') -> str:
        """
        根据指定格式输出引用列表。
        """
        if not citations:
            return ''
        # 根据前端或调用方的需求选择对应的引用输出格式。
        if format_type == 'markdown':
            return self._format_citations_markdown(citations)
        if format_type == 'html':
            return self._format_citations_html(citations)
        return self._format_citations_plain(citations)

    def _format_citations_markdown(self, citations: List[Dict[str, Any]]) -> str:
        """
        将引用列表格式化为 Markdown 形式。
        """
        lines = ['## 参考来源', '']
        for citation in citations:
            line = f"[{citation['index']}] **{citation['source_name']}**"
            if citation.get('relevance_score') is not None:
                line += f" (相关度: {citation['relevance_score']:.2f})"
            lines.append(line)
        return '\n'.join(lines)

    def _format_citations_html(self, citations: List[Dict[str, Any]]) -> str:
        """
        将引用列表格式化为 HTML 形式。
        """
        lines = ['<div class="citations">', '<h3>参考来源</h3>', '<ol>']
        for citation in citations:
            line = f'<li><strong>{citation["source_name"]}</strong>'
            if citation.get('relevance_score') is not None:
                line += f' <span class="score">(相关度: {citation["relevance_score"]:.2f})</span>'
            line += '</li>'
            lines.append(line)
        lines.extend(['</ol>', '</div>'])
        return '\n'.join(lines)

    def _format_citations_plain(self, citations: List[Dict[str, Any]]) -> str:
        """
        将引用列表格式化为纯文本形式。
        """
        lines = ['参考来源：']
        for citation in citations:
            line = f"[{citation['index']}] {citation['source_name']}"
            if citation.get('relevance_score') is not None:
                line += f" (相关度: {citation['relevance_score']:.2f})"
            lines.append(line)
        return '\n'.join(lines)

    def validate_citations(self, content: str, citations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        校验回答中的引用标记与实际提取出的来源列表是否一致。
        """
        # 对比回答中实际出现的引用编号与已构建的引用列表，判断是否存在缺漏或无效引用。
        cited_indices = self._extract_citation_indices(content)
        total_citations = len(citations)
        valid_citations = len([citation for citation in citations if citation.get('source_id')])
        citation_coverage = len(cited_indices) / total_citations if total_citations > 0 else 0
        citation_indices = {citation['index'] for citation in citations}
        unmatched_indices = [index for index in cited_indices if index not in citation_indices]
        if unmatched_indices:
            self.logger.warning('Found unmatched citation indices: %s', unmatched_indices)
        return {
            'is_valid': len(unmatched_indices) == 0,
            'total_citations': total_citations,
            'valid_citations': valid_citations,
            'citation_coverage': citation_coverage,
            'unmatched_indices': unmatched_indices,
            'cited_indices': cited_indices,
        }

    def add_citation_markers(self, content: str, retrieval_results: List[Dict[str, Any]], auto_cite: bool = False) -> str:
        """
        在需要时为回答内容自动补充引用标记。
        """
        if not auto_cite or not retrieval_results:
            return content
        self.logger.warning('Auto citation feature not implemented yet')
        return content
