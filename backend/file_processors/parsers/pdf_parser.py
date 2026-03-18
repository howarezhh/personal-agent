
import asyncio
import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable, List, Mapping, Sequence

from backend.file_processors.parsers.base_parser import BaseParser, ParsedContent


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
            try:
                result = await self._parse_with_pdfplumber(normalized_path)
                return await self._maybe_apply_ocr_fallback(normalized_path, result)
            except ImportError:
                self.logger.warning("pdfplumber not installed, falling back to PyPDF2")

            try:
                result = await self._parse_with_pypdf2(normalized_path)
                return await self._maybe_apply_ocr_fallback(normalized_path, result)
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
        if result.text:
            return result

        try:
            ocr_result = await self._ocr_pdf(file_path)
        except ImportError:
            return result
        except Exception as exc:
            self.logger.warning("PDF OCR fallback skipped: %s", exc)
            return result

        if not ocr_result or not ocr_result.text:
            return result

        merged_metadata = dict(result.metadata or {})
        merged_metadata.update(ocr_result.metadata or {})
        merged_metadata["ocr_applied"] = True
        return self.finalize_parsed_content(
            str(file_path),
            ParsedContent(
                text=ocr_result.text,
                metadata=merged_metadata,
                pages=ocr_result.pages,
                tables=result.tables,
                images=result.images,
            ),
        )

    async def _ocr_pdf(self, file_path: Path) -> ParsedContent:
        return await asyncio.to_thread(self._ocr_pdf_sync, file_path)

    def _ocr_pdf_sync(self, file_path: Path) -> ParsedContent:
        try:
            import fitz
            from PIL import Image
            import pytesseract
        except ImportError as exc:
            raise ImportError("PDF OCR fallback requires PyMuPDF, Pillow and pytesseract") from exc

        pages = []
        with fitz.open(file_path) as document:
            for page_index in range(len(document)):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                text = self._sanitize_text(pytesseract.image_to_string(image))
                if not text:
                    continue
                pages.append({"page_number": page_index + 1, "text": text, "char_count": len(text)})

        full_text = "\n\n".join(page["text"] for page in pages)
        return ParsedContent(
            text=full_text,
            metadata={
                "parser": "pdf_ocr",
                "ocr_engine": "pytesseract",
                "total_pages": len(pages),
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
        return file_extension.lower() in [".pdf"]

    def get_supported_extensions(self) -> List[str]:
        return [".pdf"]
