from __future__ import annotations

import asyncio
import os
import re
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable, List, Mapping, Sequence

from backend.file_processors.parsers.base_parser import BaseParser, ParsedContent
from backend.file_processors.parsers.ocr_engines import extract_text_from_image, get_ocr_runtime_hint


class PDFParser(BaseParser):
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
        super().__init__()

    async def parse(self, file_path: str) -> ParsedContent:
        normalized_path = self._validate_file_path(file_path)

        try:
            # 优先使用 pdfplumber；若解析异常则继续尝试 PyPDF2，避免单后端失败即整体失败。
            parse_errors: list[Exception] = []
            extracted_result: ParsedContent | None = None
            for backend_name, backend_parser in (
                ("pdfplumber", self._parse_with_pdfplumber),
                ("PyPDF2", self._parse_with_pypdf2),
            ):
                try:
                    extracted_result = await backend_parser(normalized_path)
                    break
                except ImportError as exc:
                    parse_errors.append(exc)
                    self.logger.warning("%s not available, trying next PDF backend", backend_name)
                except Exception as exc:
                    parse_errors.append(exc)
                    self.logger.warning("%s failed to parse PDF, trying next backend: %s", backend_name, exc)

            if extracted_result is None:
                non_import_errors = [error for error in parse_errors if not isinstance(error, ImportError)]
                if non_import_errors:
                    raise non_import_errors[-1]
                raise ImportError("Neither pdfplumber nor PyPDF2 is installed. Please install one of them.")

            return await self._maybe_apply_ocr_fallback(normalized_path, extracted_result)
        except ImportError as exc:
            raise ImportError(
                "Neither pdfplumber nor PyPDF2 is installed. Please install one of them."
            ) from exc
        except Exception as exc:
            self.logger.error("Failed to parse PDF: %s", exc, exc_info=True)
            raise

    async def _parse_with_pdfplumber(self, file_path: Path) -> ParsedContent:
        return await asyncio.to_thread(self._parse_with_pdfplumber_sync, file_path)

    async def _parse_with_pypdf2(self, file_path: Path) -> ParsedContent:
        return await asyncio.to_thread(self._parse_with_pypdf2_sync, file_path)

    async def _maybe_apply_ocr_fallback(self, file_path: Path, result: ParsedContent) -> ParsedContent:
        pages = [dict(page) for page in result.pages or []]
        target_page_numbers = [
            int(page.get("page_number"))
            for page in pages
            if page.get("page_number") is not None and self._page_needs_ocr(page)
        ]

        if not pages:
            target_page_numbers = list(range(1, int((result.metadata or {}).get("total_pages", 0)) + 1))

        if not target_page_numbers:
            return result

        try:
            ocr_result = await self._ocr_pdf(file_path, target_page_numbers)
        except ImportError as exc:
            metadata = dict(result.metadata or {})
            metadata.setdefault("ocr_available", False)
            metadata.setdefault("ocr_skipped_reason", str(exc))
            return ParsedContent(
                text=result.text,
                metadata=metadata,
                pages=result.pages,
                tables=result.tables,
                images=result.images,
                blocks=result.blocks,
            )
        except Exception as exc:
            self.logger.warning("PDF OCR fallback skipped: %s", exc)
            metadata = dict(result.metadata or {})
            metadata.setdefault("ocr_available", False)
            metadata.setdefault("ocr_skipped_reason", str(exc))
            return ParsedContent(
                text=result.text,
                metadata=metadata,
                pages=result.pages,
                tables=result.tables,
                images=result.images,
                blocks=result.blocks,
            )

        ocr_pages = {int(page["page_number"]): dict(page) for page in (ocr_result.pages or []) if page.get("text")}
        if not ocr_pages:
            return result

        merged_pages: List[dict[str, Any]] = []
        applied_ocr_pages: List[int] = []
        source_pages = pages or []
        if not source_pages:
            source_pages = [
                {"page_number": page_number, "text": "", "char_count": 0}
                for page_number in target_page_numbers
            ]

        for page in source_pages:
            page_number = int(page.get("page_number") or 0)
            ocr_page = ocr_pages.get(page_number)
            merged_page = dict(page)
            if ocr_page and ocr_page.get("text"):
                merged_page["text"] = ocr_page["text"]
                merged_page["char_count"] = len(ocr_page["text"])
                merged_page["ocr_applied"] = True
                merged_page["text_source"] = "ocr"
                applied_ocr_pages.append(page_number)
            else:
                merged_page["ocr_applied"] = False
                merged_page["text_source"] = merged_page.get("text_source") or "extract"
            merged_pages.append(merged_page)

        merged_pages = self._apply_page_start_offsets(merged_pages)

        merged_metadata = dict(result.metadata or {})
        merged_metadata["ocr_applied"] = bool(applied_ocr_pages)
        merged_metadata["ocr_page_numbers"] = applied_ocr_pages
        if ocr_result.metadata.get("ocr_engine"):
            merged_metadata["ocr_engine"] = ocr_result.metadata.get("ocr_engine")

        full_text = "\n\n".join(str(page.get("text") or "") for page in merged_pages if page.get("text"))
        merged_metadata["has_text"] = bool(full_text)
        merged_metadata["empty_content"] = not bool(full_text)
        return ParsedContent(
            text=full_text,
            metadata=merged_metadata,
            pages=merged_pages,
            tables=result.tables,
            images=result.images,
        )

    async def _ocr_pdf(self, file_path: Path, page_numbers: Sequence[int]) -> ParsedContent:
        return await asyncio.to_thread(self._ocr_pdf_sync, file_path, list(page_numbers))

    def _ocr_pdf_sync(self, file_path: Path, page_numbers: List[int]) -> ParsedContent:
        try:
            import fitz
            from PIL import Image
        except ImportError as exc:
            raise ImportError("PDF OCR fallback requires PyMuPDF and Pillow") from exc

        requested_pages = {int(page_number) for page_number in page_numbers if int(page_number) > 0}
        pages = []
        engines_used: set[str] = set()
        with fitz.open(file_path) as document:
            for page_index in range(len(document)):
                page_number = page_index + 1
                if requested_pages and page_number not in requested_pages:
                    continue

                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                text, ocr_engine = extract_text_from_image(image)
                engines_used.add(ocr_engine)
                text = self._sanitize_text(text)
                pages.append(
                    {
                        "page_number": page_number,
                        "text": text,
                        "char_count": len(text),
                        "ocr_applied": True,
                        "text_source": "ocr",
                        "ocr_engine": ocr_engine,
                    }
                )

        pages = self._apply_page_start_offsets(pages)
        full_text = "\n\n".join(page["text"] for page in pages if page["text"])
        return ParsedContent(
            text=full_text,
            metadata={
                "parser": "pdf_ocr",
                "ocr_engine": ",".join(sorted(engines_used)) if engines_used else get_ocr_runtime_hint(),
                "total_pages": len(page_numbers),
                "has_text": bool(full_text),
                "empty_content": not bool(full_text),
            },
            pages=pages,
        )

    def _parse_with_pdfplumber_sync(self, file_path: Path) -> ParsedContent:
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
            full_text = "\n\n".join(page["text"] for page in pages_info if page.get("text"))

            metadata["has_text"] = bool(full_text)
            metadata["empty_content"] = not bool(full_text)

            if not full_text:
                self.logger.warning("PDF contains no extractable text: %s", file_path)

            return ParsedContent(text=full_text, metadata=metadata, pages=pages_info)

    def _validate_file_path(self, file_path: str) -> Path:
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
        pages_info: List[dict[str, Any]] = []

        for page_num, page in enumerate(pages, start=1):
            try:
                raw_text = text_extractor(page)
            except Exception as exc:
                self.logger.warning("Failed to extract text from page %s: %s", page_num, exc)
                raw_text = ""

            text = self._sanitize_text(raw_text)
            pages_info.append(
                {
                    "page_number": page_num,
                    "text": text,
                    "char_count": len(text),
                    "ocr_applied": False,
                    "text_source": "extract",
                }
            )

        return self._apply_page_start_offsets(pages_info)

    @staticmethod
    def _apply_page_start_offsets(pages: List[dict[str, Any]]) -> List[dict[str, Any]]:
        """为分页结果补齐全局字符偏移，便于后续切块位置稳定。"""
        current_offset = 0
        normalized_pages: List[dict[str, Any]] = []
        for page in pages or []:
            normalized_page = dict(page)
            normalized_page["start_char"] = current_offset
            page_text = str(normalized_page.get("text") or "")
            current_offset += len(page_text) + 2
            normalized_pages.append(normalized_page)
        return normalized_pages

    def _page_needs_ocr(self, page: Mapping[str, Any]) -> bool:
        """判断当前页是否缺少足够的可读文本，需回退到 OCR。"""
        text = str(page.get("text") or "")
        if not text.strip():
            return True

        meaningful_characters = [character for character in text if character.isalnum() or self._is_cjk_char(character)]
        return len(meaningful_characters) < 4

    @staticmethod
    def _is_cjk_char(character: str) -> bool:
        """判断字符是否属于常用中日韩统一表意文字区。

        这里与 chunker 中的判断逻辑保持一致，避免中文页因为 `isalnum()`
        覆盖不稳定而被错误判定为“无有效文本”。
        """
        return bool(character and "\u4e00" <= character <= "\u9fff")

    def _sanitize_text(self, value: Any) -> str:
        return self._clean_text_value(
            value,
            self._get_text_cleaning_profile(".pdf"),
        )

    def supports(self, file_extension: str) -> bool:
        return file_extension.lower() in [".pdf"]

    def get_supported_extensions(self) -> List[str]:
        return [".pdf"]
