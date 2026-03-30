# -*- coding: utf-8 -*-

"""Parser registry.

解析器注册表不再手写维护 `FileType -> parser` 映射，
而是统一复用 `document_registry` 中的权威定义，避免扩展名、MIME、parser 漂移。
"""

from __future__ import annotations

from typing import Any

from backend.file_processors.document_registry import get_parser_key_for_file_type, iter_document_formats
from backend.file_processors.parsers.base_parser import BaseParser
from backend.file_processors.parsers.excel_text_parser import ExcelParser, TabularParser, TextParser
from backend.file_processors.parsers.html_parser import HtmlParser
from backend.file_processors.parsers.image_ocr_parser import ImageOCRParser
from backend.file_processors.parsers.pdf_parser import PDFParser
from backend.file_processors.parsers.pptx_parser import PptxParser
from backend.file_processors.parsers.word_parser import WordParser


class ParserRegistry:
    """解析器实例注册表。"""

    def __init__(self):
        self._parsers: dict[str, BaseParser] = {}

    def register(self, key: str, parser: BaseParser):
        self._parsers[key] = parser

    def get(self, parser_key: str | None):
        if not parser_key:
            return None
        return self._parsers.get(parser_key)

    def get_for_file_type(self, file_type: Any):
        """按 FileType 获取解析器，真正的映射规则来自统一文档注册表。"""
        return self.get(get_parser_key_for_file_type(file_type))

    def all(self):
        return dict(self._parsers)


_parser_registry: ParserRegistry | None = None


def get_parser_registry() -> ParserRegistry:
    """Get the global parser registry and populate it on first access."""
    global _parser_registry
    if _parser_registry is None:
        _parser_registry = ParserRegistry()
        parser_factories = {
            "pdf": PDFParser,
            "word": WordParser,
            "pptx": PptxParser,
            "excel": ExcelParser,
            "tabular": TabularParser,
            "html": HtmlParser,
            "image": ImageOCRParser,
            "text": TextParser,
        }

        # 只注册统一注册表里真正声明过的 parser，避免再出现“代码里有 parser，配置里没有”的漂移。
        for parser_key in dict.fromkeys(spec.parser_key for spec in iter_document_formats() if spec.parser_key):
            factory = parser_factories.get(parser_key)
            if factory is None:
                raise ValueError(f"Parser key `{parser_key}` 未在 parser_factories 中注册")
            _parser_registry.register(parser_key, factory())
    return _parser_registry
