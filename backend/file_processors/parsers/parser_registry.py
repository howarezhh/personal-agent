# -*- coding: utf-8 -*-

"""Parser registry.

Maintains the mapping from file type to parser instance.
Shared by `backend.file_processors` and `FileProcessorAgent`.
"""

from __future__ import annotations

from backend.file_processors.parsers.base_parser import BaseParser
from backend.file_processors.parsers.excel_text_parser import ExcelParser, TextParser
from backend.file_processors.parsers.html_parser import HtmlParser
from backend.file_processors.parsers.image_ocr_parser import ImageOCRParser
from backend.file_processors.parsers.pdf_parser import PDFParser
from backend.file_processors.parsers.pptx_parser import PptxParser
from backend.file_processors.parsers.word_parser import WordParser


class ParserRegistry:
    """Registry implementation for parser instances."""

    def __init__(self):
        self._parsers: dict[str, BaseParser] = {}

    def register(self, key: str, parser: BaseParser):
        """Register a parser."""
        self._parsers[key] = parser

    def get(self, file_type: str):
        """Get a parser by file type."""
        return self._parsers.get(file_type)

    def all(self):
        """Return all registered parsers."""
        return dict(self._parsers)


_parser_registry: ParserRegistry | None = None


def get_parser_registry() -> ParserRegistry:
    """Get the global parser registry and populate it on first access."""
    global _parser_registry
    if _parser_registry is None:
        _parser_registry = ParserRegistry()
        _parser_registry.register("pdf", PDFParser())
        _parser_registry.register("word", WordParser())
        _parser_registry.register("pptx", PptxParser())
        _parser_registry.register("excel", ExcelParser())
        _parser_registry.register("html", HtmlParser())
        _parser_registry.register("image", ImageOCRParser())
        _parser_registry.register("text", TextParser())
    return _parser_registry
