"""文件解析器注册表模块

提供文件解析器的统一注册和管理机制，支持多种文件格式的解析器动态注册和获取。
"""

# 导入基础解析器类和各类具体解析器实现
from backend.file_processors.parsers.base_parser import BaseParser
from backend.file_processors.parsers.excel_text_parser import ExcelParser, TextParser
from backend.file_processors.parsers.pdf_parser import PDFParser
from backend.file_processors.parsers.word_parser import WordParser


class ParserRegistry:
    """文件解析器注册表类
    
    负责管理所有可用的文件解析器实例，提供注册、查询和获取解析器的功能。
    采用字典结构存储，以文件类型为键，解析器实例为值。
    """
    
    def __init__(self):
        """初始化解析器注册表
        
        创建一个空字典用于存储已注册的解析器。
        """
        self._parsers: dict[str, BaseParser] = {}

    def register(self, key: str, parser: BaseParser):
        """注册文件解析器
        
        Args:
            key (str): 文件类型标识符，如 'pdf', 'word', 'excel', 'text'
            parser (BaseParser): 具体的解析器实例，必须继承自 BaseParser
        """
        self._parsers[key] = parser

    def get(self, file_type: str):
        """根据文件类型获取对应的解析器
        
        Args:
            file_type (str): 文件类型标识符
            
        Returns:
            BaseParser | None: 返回匹配的解析器实例，如果未找到则返回 None
        """
        return self._parsers.get(file_type)

    def all(self):
        """获取所有已注册的解析器
        
        Returns:
            dict[str, BaseParser]: 包含所有已注册解析器的字典副本
        """
        return dict(self._parsers)


# 全局解析器注册表实例（单例模式）
_parser_registry: ParserRegistry | None = None


def get_parser_registry() -> ParserRegistry:
    """获取全局解析器注册表实例
    
    采用懒加载方式创建并初始化解析器注册表，确保全局唯一实例。
    首次调用时会自动注册所有内置的文件解析器。
    
    Returns:
        ParserRegistry: 全局解析器注册表实例
        
    Note:
        该函数会注册以下内置解析器：
        - pdf: PDF 文件解析器
        - word: Word 文档解析器
        - excel: Excel 表格解析器
        - text: 纯文本文件解析器
    """
    global _parser_registry
    if _parser_registry is None:
        # 创建注册表实例并注册所有内置解析器
        _parser_registry = ParserRegistry()
        _parser_registry.register("pdf", PDFParser())
        _parser_registry.register("word", WordParser())
        _parser_registry.register("excel", ExcelParser())
        _parser_registry.register("text", TextParser())
    return _parser_registry
