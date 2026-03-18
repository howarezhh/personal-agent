# -*- coding: utf-8 -*-

"""文件处理能力统一导出层。

该目录负责文件解析、文本清洗、分块等“文件处理实现能力”。
`backend/agents/file_processor/` 则只负责 Agent 编排入口。
通过该导出层，外部调用方无需再直接依赖内部 `parsers/` 目录结构。
"""

from backend.file_processors.chunker import DocumentChunker
from backend.file_processors.parsers import (
    BaseParser,
    ParsedContent,
    ParserRegistry,
    TextCleaningProfile,
    get_parser_registry,
)

__all__ = [
    "BaseParser",
    "DocumentChunker",
    "ParsedContent",
    "ParserRegistry",
    "TextCleaningProfile",
    "get_parser_registry",
]
