
# 导入基础解析器类和各类具体解析器实现
from backend.file_processors.parsers.base_parser import BaseParser
from backend.file_processors.parsers.excel_text_parser import ExcelParser, TextParser
from backend.file_processors.parsers.pdf_parser import PDFParser
from backend.file_processors.parsers.word_parser import WordParser


class ParserRegistry:
    def __init__(self):
        self._parsers: dict[str, BaseParser] = {}

    def register(self, key: str, parser: BaseParser):
        self._parsers[key] = parser

    def get(self, file_type: str):
        return self._parsers.get(file_type)

    def all(self):
        return dict(self._parsers)


# 全局解析器注册表实例（单例模式）
_parser_registry: ParserRegistry | None = None


def get_parser_registry() -> ParserRegistry:
    global _parser_registry
    if _parser_registry is None:
        # 创建注册表实例并注册所有内置解析器
        _parser_registry = ParserRegistry()
        _parser_registry.register("pdf", PDFParser())
        _parser_registry.register("word", WordParser())
        _parser_registry.register("excel", ExcelParser())
        _parser_registry.register("text", TextParser())
    return _parser_registry
