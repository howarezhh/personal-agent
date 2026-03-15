from __future__ import annotations

import re
from typing import Any


def resolve_source_name(payload: dict[str, Any] | None, default: str = 'Unknown') -> str:
    if not isinstance(payload, dict):
        return default

    for key in (
        'source_name',
        'source',
        'sourceName',
        'file_name',
        'fileName',
        'original_filename',
        'originalFilename',
        'document_name',
        'documentName',
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    metadata = payload.get('metadata')
    if isinstance(metadata, dict):
        return resolve_source_name(metadata, default=default)

    return default


def replace_citation_placeholders(answer: str, citations: list[dict[str, Any]] | None) -> str:
    if not answer or not citations:
        return answer

    normalized_answer = answer
    for index, citation in enumerate(citations, start=1):
        source_name = resolve_source_name(citation, default=f'来源{index}')
        replacement = f'【{source_name}】'
        patterns = [
            rf'\[来源{index}\]',
            rf'\[参考{index}\]',
            rf'【来源{index}】',
            rf'【参考{index}】',
            rf'\[{index}\]',
            rf'【{index}】',
            rf'\({index}\)',
        ]
        for pattern in patterns:
            normalized_answer = re.sub(pattern, replacement, normalized_answer)

    return normalized_answer


def normalize_message_content_with_citations(content: str, metadata: dict[str, Any] | None) -> str:
    if not content or not isinstance(metadata, dict):
        return content

    citations = metadata.get('citations')
    if not isinstance(citations, list):
        return content

    return replace_citation_placeholders(content, citations)
