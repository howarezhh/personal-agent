from __future__ import annotations

import re
from typing import Any


_CITATION_MARKER_TEMPLATES = (
    '[来源{index}]',
    '[参考{index}]',
    '【来源{index}】',
    '【参考{index}】',
    '[{index}]',
    '【{index}】',
    '({index})',
)


def resolve_source_name(payload: dict[str, Any] | None, default: str = 'Unknown') -> str:
    if not isinstance(payload, dict):
        return default

    # 历史数据里 `source` 可能被错误写成知识库名，因此这里优先返回具体文档名字段。
    for key in (
        'file_name',
        'fileName',
        'original_filename',
        'originalFilename',
        'document_name',
        'documentName',
        'source_name',
        'sourceName',
        'source',
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    metadata = payload.get('metadata')
    if isinstance(metadata, dict):
        return resolve_source_name(metadata, default=default)

    return default


def _build_citation_patterns(index: int) -> tuple[str, ...]:
    return (
        rf'\[来源{index}\]',
        rf'\[参考{index}\]',
        rf'【来源{index}】',
        rf'【参考{index}】',
        rf'\[{index}\]',
        rf'【{index}】',
        rf'\({index}\)',
    )


def _build_citation_markers(index: int) -> tuple[str, ...]:
    return tuple(template.format(index=index) for template in _CITATION_MARKER_TEMPLATES)


def _repair_nested_citation_replacements(answer: str, citations: list[dict[str, Any]]) -> str:
    repaired_answer = answer

    for index, citation in enumerate(citations, start=1):
        source_name = resolve_source_name(citation, default=f'来源{index}')
        replacement = f'【{source_name}】'
        nested_variants = {
            f'【{source_name.replace(marker, replacement)}】'
            for marker in _build_citation_markers(index)
            if marker in source_name
        }

        changed = True
        while changed:
            changed = False
            for variant in sorted(nested_variants, key=len, reverse=True):
                if variant != replacement and variant in repaired_answer:
                    repaired_answer = repaired_answer.replace(variant, replacement)
                    changed = True

    return repaired_answer


def replace_citation_placeholders(answer: str, citations: list[dict[str, Any]] | None) -> str:
    if not answer or not citations:
        return answer

    normalized_answer = answer
    replacements: dict[str, str] = {}

    for index, citation in enumerate(citations, start=1):
        source_name = resolve_source_name(citation, default=f'来源{index}')
        replacement = f'【{source_name}】'
        token = f'__CITATION_PLACEHOLDER_{index}__'
        replacements[token] = replacement

        for pattern in _build_citation_patterns(index):
            normalized_answer = re.sub(pattern, token, normalized_answer)

    for token, replacement in replacements.items():
        normalized_answer = normalized_answer.replace(token, replacement)

    return _repair_nested_citation_replacements(normalized_answer, citations)


def normalize_message_content_with_citations(content: str, metadata: dict[str, Any] | None) -> str:
    if not content or not isinstance(metadata, dict):
        return content

    citations = metadata.get('citations')
    if not isinstance(citations, list):
        return content

    return replace_citation_placeholders(content, citations)
