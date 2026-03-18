# -*- coding: utf-8 -*-

"""文件解析器子包统一导出层。"""

from backend.file_processors.parsers.base_parser import BaseParser, ParsedContent, TextCleaningProfile
from backend.file_processors.parsers.parser_registry import ParserRegistry, get_parser_registry

__all__ = [
    "BaseParser",
    "ParsedContent",
    "ParserRegistry",
    "TextCleaningProfile",
    "get_parser_registry",
]
