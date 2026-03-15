
from __future__ import annotations

import re
from typing import Any, Dict, List

from backend.utils.citation_utils import resolve_source_name
from backend.utils.logger import get_logger


class SourceExtractor:
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
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
        all_indices: set[int] = set()
        for pattern in self.citation_patterns:
            for match in re.findall(pattern, content):
                try:
                    all_indices.add(int(match))
                except (TypeError, ValueError):
                    continue
        return sorted(all_indices)

    def format_citations(self, citations: List[Dict[str, Any]], format_type: str = 'markdown') -> str:
        if not citations:
            return ''
        if format_type == 'markdown':
            return self._format_citations_markdown(citations)
        if format_type == 'html':
            return self._format_citations_html(citations)
        return self._format_citations_plain(citations)

    def _format_citations_markdown(self, citations: List[Dict[str, Any]]) -> str:
        lines = ['## 参考来源', '']
        for citation in citations:
            line = f"[{citation['index']}] **{citation['source_name']}**"
            if citation.get('relevance_score') is not None:
                line += f" (相关度: {citation['relevance_score']:.2f})"
            lines.append(line)
        return '\n'.join(lines)

    def _format_citations_html(self, citations: List[Dict[str, Any]]) -> str:
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
        lines = ['参考来源：']
        for citation in citations:
            line = f"[{citation['index']}] {citation['source_name']}"
            if citation.get('relevance_score') is not None:
                line += f" (相关度: {citation['relevance_score']:.2f})"
            lines.append(line)
        return '\n'.join(lines)

    def validate_citations(self, content: str, citations: List[Dict[str, Any]]) -> Dict[str, Any]:
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
        if not auto_cite or not retrieval_results:
            return content
        self.logger.warning('Auto citation feature not implemented yet')
        return content
