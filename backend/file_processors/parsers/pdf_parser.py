"""
PDF 文件解析器模块

提供 PDF 文件的解析功能，支持使用 pdfplumber 或 PyPDF2 库提取 PDF 内容。
优先使用 pdfplumber（文本提取效果更好），如果未安装则降级使用 PyPDF2。

主要功能：
- 提取 PDF 文本内容
- 保留页码和页面信息
- 提取元数据（作者、标题、主题等）
- 支持异步解析
"""

import asyncio
import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable, List, Mapping, Sequence

from backend.file_processors.parsers.base_parser import BaseParser, ParsedContent


class PDFParser(BaseParser):
    """
    PDF 文件解析器类

    继承自 BaseParser，实现 PDF 格式文件的具体解析逻辑。
    采用双库策略：优先使用 pdfplumber 获得更好的文本提取效果，
    如果未安装则自动降级使用 PyPDF2。

    主要功能：
    - 提取文本内容：从 PDF 各页中提取可读文本
    - 保留页码信息：记录每页的页码和对应文本
    - 提取元数据：获取 PDF 的作者、标题、主题等元信息
    - 异步处理：将阻塞式 PDF 解析卸载到线程池，避免阻塞事件循环

    Attributes:
        logger: 日志记录器，用于记录解析过程中的信息和错误
    """

    _PDFPLUMBER_METADATA_KEYS = {
        "title": ("Title",),
        "author": ("Author",),
        "subject": ("Subject",),
        "creator": ("Creator",),
    }
    _PYPDF2_METADATA_KEYS = {
        "title": ("/Title",),
        "author": ("/Author",),
        "subject": ("/Subject",),
        "creator": ("/Creator",),
    }

    def __init__(self):
        """
        初始化 PDF 解析器

        调用父类 BaseParser 的初始化方法，设置日志记录器等基础组件。
        """
        super().__init__()

    async def parse(self, file_path: str) -> ParsedContent:
        """
        解析 PDF 文件的主方法

        采用降级策略解析 PDF 文件：
        1. 首先尝试使用 pdfplumber（推荐，文本提取效果更好）
        2. 如果 pdfplumber 不可用，降级使用 PyPDF2
        3. 如果两个库都不可用，抛出 ImportError

        Args:
            file_path (str): PDF 文件的路径

        Returns:
            ParsedContent: 包含解析后的文本、元数据和页面信息的对象

        Raises:
            FileNotFoundError: 文件不存在时抛出
            PermissionError: 文件不可读时抛出
            ImportError: 当 pdfplumber 和 PyPDF2 都未安装时抛出
            Exception: 其他解析过程中的错误
        """
        normalized_path = self._validate_file_path(file_path)

        try:
            try:
                return await self._parse_with_pdfplumber(normalized_path)
            except ImportError:
                self.logger.warning("pdfplumber not installed, falling back to PyPDF2")

            try:
                return await self._parse_with_pypdf2(normalized_path)
            except ImportError as exc:
                raise ImportError(
                    "Neither pdfplumber nor PyPDF2 is installed. Please install one of them."
                ) from exc
        except Exception as exc:
            self.logger.error("Failed to parse PDF: %s", exc, exc_info=True)
            raise

    async def _parse_with_pdfplumber(self, file_path: Path) -> ParsedContent:
        """在线程池中使用 pdfplumber 解析 PDF，避免阻塞事件循环。"""
        return await asyncio.to_thread(self._parse_with_pdfplumber_sync, file_path)

    async def _parse_with_pypdf2(self, file_path: Path) -> ParsedContent:
        """在线程池中使用 PyPDF2 解析 PDF，避免阻塞事件循环。"""
        return await asyncio.to_thread(self._parse_with_pypdf2_sync, file_path)

    def _parse_with_pdfplumber_sync(self, file_path: Path) -> ParsedContent:
        """使用 pdfplumber 同步解析 PDF 文件。"""
        import pdfplumber

        return self._parse_with_backend(
            file_path=file_path,
            parser_name="pdfplumber",
            document_loader=lambda file_obj: pdfplumber.open(file_obj),
            metadata_getter=lambda document: document.metadata,
            metadata_keys=self._PDFPLUMBER_METADATA_KEYS,
            pages_getter=lambda document: document.pages,
            text_extractor=lambda page: page.extract_text(),
        )

    def _parse_with_pypdf2_sync(self, file_path: Path) -> ParsedContent:
        """使用 PyPDF2 同步解析 PDF 文件。"""
        import PyPDF2

        return self._parse_with_backend(
            file_path=file_path,
            parser_name="PyPDF2",
            document_loader=lambda file_obj: PyPDF2.PdfReader(file_obj),
            metadata_getter=lambda document: document.metadata,
            metadata_keys=self._PYPDF2_METADATA_KEYS,
            pages_getter=lambda document: document.pages,
            text_extractor=lambda page: page.extract_text(),
        )

    def _parse_with_backend(
        self,
        file_path: Path,
        parser_name: str,
        document_loader: Callable[[Any], Any],
        metadata_getter: Callable[[Any], Any],
        metadata_keys: Mapping[str, Sequence[str]],
        pages_getter: Callable[[Any], Sequence[Any]],
        text_extractor: Callable[[Any], Any],
    ) -> ParsedContent:
        """
        使用统一流程解析 PDF，减少 pdfplumber 与 PyPDF2 的重复逻辑。

        Args:
            file_path: PDF 文件路径
            parser_name: 解析器名称
            document_loader: 文档加载函数
            metadata_getter: 文档元数据提取函数
            metadata_keys: 元数据字段映射
            pages_getter: 页面序列获取函数
            text_extractor: 页面文本提取函数

        Returns:
            ParsedContent: 标准化后的解析结果
        """
        with file_path.open("rb") as file_obj, ExitStack() as stack:
            document = document_loader(file_obj)
            if hasattr(document, "__enter__") and hasattr(document, "__exit__"):
                document = stack.enter_context(document)

            pages = pages_getter(document)
            metadata = self._build_metadata(
                total_pages=len(pages),
                parser_name=parser_name,
                raw_metadata=metadata_getter(document),
                metadata_keys=metadata_keys,
            )
            pages_info = self._extract_pages_info(pages, text_extractor)
            full_text = "\n\n".join(page["text"] for page in pages_info)

            metadata["has_text"] = bool(full_text)
            metadata["empty_content"] = not bool(full_text)

            if not full_text:
                self.logger.warning("PDF contains no extractable text: %s", file_path)

            return self.finalize_parsed_content(
                str(file_path),
                ParsedContent(text=full_text, metadata=metadata, pages=pages_info),
            )

    def _validate_file_path(self, file_path: str) -> Path:
        """校验 PDF 路径有效性并确保文件可读。"""
        if not file_path or not str(file_path).strip():
            raise ValueError("PDF file path cannot be empty.")

        path = Path(file_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"PDF file does not exist: {path}")
        if not path.is_file():
            raise ValueError(f"PDF path is not a file: {path}")
        if not os.access(path, os.R_OK):
            raise PermissionError(f"PDF file is not readable: {path}")

        return path

    def _build_metadata(
        self,
        total_pages: int,
        parser_name: str,
        raw_metadata: Any,
        metadata_keys: Mapping[str, Sequence[str]],
    ) -> dict[str, Any]:
        """标准化 PDF 元数据，并处理编码异常字符。"""
        metadata: dict[str, Any] = {
            "total_pages": total_pages,
            "parser": parser_name,
        }

        if not raw_metadata:
            return metadata

        for target_key, source_keys in metadata_keys.items():
            metadata[target_key] = self._sanitize_text(self._read_metadata_value(raw_metadata, source_keys))

        return metadata

    def _read_metadata_value(self, raw_metadata: Any, source_keys: Sequence[str]) -> Any:
        """按候选键顺序读取元数据字段。"""
        for source_key in source_keys:
            value = None

            if hasattr(raw_metadata, "get"):
                value = raw_metadata.get(source_key)
            else:
                try:
                    value = raw_metadata[source_key]
                except Exception:
                    value = None

            if value not in (None, ""):
                return value

        return None

    def _extract_pages_info(
        self,
        pages: Sequence[Any],
        text_extractor: Callable[[Any], Any],
    ) -> List[dict[str, Any]]:
        """提取各页文本并统一清洗，避免重复拼装逻辑。"""
        pages_info: List[dict[str, Any]] = []

        for page_num, page in enumerate(pages, start=1):
            try:
                raw_text = text_extractor(page)
            except Exception as exc:
                self.logger.warning("Failed to extract text from page %s: %s", page_num, exc)
                continue

            text = self._sanitize_text(raw_text)
            if not text:
                continue

            pages_info.append(
                {
                    "page_number": page_num,
                    "text": text,
                    "char_count": len(text),
                }
            )

        return pages_info

    def _sanitize_text(self, value: Any) -> str:
        return self._clean_text_value(
            value,
            self._get_text_cleaning_profile('.pdf'),
        )

    def supports(self, file_extension: str) -> bool:
        """
        检查是否支持指定的文件扩展名

        Args:
            file_extension (str): 文件扩展名（如 '.pdf'）

        Returns:
            bool: 如果支持该扩展名返回 True，否则返回 False
        """
        return file_extension.lower() in [".pdf"]

    def get_supported_extensions(self) -> List[str]:
        """
        获取此解析器支持的所有文件扩展名

        Returns:
            List[str]: 支持的文件扩展名列表
        """
        return [".pdf"]
