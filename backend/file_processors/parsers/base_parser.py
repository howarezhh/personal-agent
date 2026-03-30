
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional


@dataclass
class ParsedContent:
    text: str
    metadata: Dict[str, Any]
    pages: Optional[List[Dict[str, Any]]] = None
    tables: Optional[List[Dict[str, Any]]] = None
    images: Optional[List[Dict[str, Any]]] = None
    blocks: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "metadata": self.metadata,
            "pages": self.pages,
            "tables": self.tables,
            "images": self.images,
            "blocks": self.blocks,
        }


@dataclass(frozen=True)
class TextCleaningProfile:
    preserve_line_breaks: bool = False
    merge_paragraph_lines: bool = True
    preserve_indentation: bool = False
    deduplicate_consecutive_lines: bool = True


class BaseParser(ABC):
    MAX_FILE_SIZE = 50 * 1024 * 1024

    _STRUCTURED_EXTENSIONS = {
        ".json",
        ".xml",
        ".svg",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".env",
        ".properties",
        ".csv",
        ".tsv",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".cc",
        ".cpp",
        ".cxx",
        ".c",
        ".h",
        ".hpp",
        ".cs",
        ".go",
        ".rb",
        ".php",
        ".rs",
        ".swift",
        ".kt",
        ".kts",
        ".scala",
        ".sh",
        ".bash",
        ".zsh",
        ".bat",
        ".ps1",
        ".sql",
        ".html",
        ".gitignore",
        ".css",
        ".scss",
        ".less",
        ".vue",
    }
    _MARKUP_EXTENSIONS = {".md", ".markdown", ".rst"}
    _BULLET_LINE_RE = re.compile(
        r"^(?:[-*•●▪■]|(?:\(?\d+\)?[.)、])|(?:[A-Za-z][.)])|(?:[一二三四五六七八九十]+[、.]))\s+"
    )
    _PAGE_NUMBER_PATTERNS = (
        re.compile(r"^\d+$"),
        re.compile(r"^page\s+\d+(?:\s*(?:/|of)\s*\d+)?$", re.IGNORECASE),
        re.compile(r"^第\s*\d+\s*页(?:\s*/\s*共\s*\d+\s*页)?$"),
        re.compile(r"^[ivxlcdm]+$", re.IGNORECASE),
    )

    def __init__(self, max_file_size: int | None = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.max_file_size = max_file_size if max_file_size is not None else self.MAX_FILE_SIZE

    @abstractmethod
    async def parse(self, file_path: str) -> ParsedContent:
        raise NotImplementedError

    @abstractmethod
    def supports(self, file_extension: str) -> bool:
        raise NotImplementedError

    def supported_types(self) -> List[str]:
        return self.get_supported_extensions()

    def get_supported_extensions(self) -> List[str]:
        return []

    async def safe_parse(self, file_path: str) -> Dict[str, Any]:
        try:
            file_size = os.path.getsize(file_path)

            if file_size > self.max_file_size:
                error_msg = (
                    f"文件过大: {file_size / (1024 * 1024):.2f}MB, "
                    f"最大允许 {self.max_file_size / (1024 * 1024):.2f}MB"
                )
                self.logger.warning(error_msg)
                return {"success": False, "content": None, "error": error_msg}

            self.logger.info(f"Parsing file: {file_path} (size: {file_size / 1024:.2f}KB)")
            content = await self.parse(file_path)
            content = self.finalize_parsed_content(file_path, content)

            self.logger.info(f"File parsed successfully: {file_path}")
            return {"success": True, "content": content, "error": None}

        except Exception as exc:
            self.logger.error(f"Failed to parse file: {str(exc)}", exc_info=True)
            return {"success": False, "content": None, "error": f"文件解析失败: {str(exc)}"}

    def finalize_parsed_content(self, file_path: str, content: ParsedContent) -> ParsedContent:
        if content is None:
            raise ValueError("Parsed content cannot be None")

        extension = Path(file_path).suffix.lower()
        text_profile = self._get_text_cleaning_profile(extension)
        metadata_profile = TextCleaningProfile(
            preserve_line_breaks=True,
            merge_paragraph_lines=False,
            preserve_indentation=False,
            deduplicate_consecutive_lines=False,
        )

        content.metadata = self._clean_nested_value(content.metadata or {}, metadata_profile)

        if content.pages is not None:
            page_profile = TextCleaningProfile(
                preserve_line_breaks=True,
                merge_paragraph_lines=False,
                preserve_indentation=False,
                deduplicate_consecutive_lines=text_profile.deduplicate_consecutive_lines,
            )
            cleaned_pages: List[Dict[str, Any]] = []
            for page in content.pages:
                if not isinstance(page, dict):
                    continue

                cleaned_page = dict(page)
                cleaned_page["text"] = self._clean_text_value(page.get("text", ""), page_profile)
                cleaned_page["char_count"] = len(cleaned_page["text"])
                cleaned_pages.append(cleaned_page)

            cleaned_pages = self._strip_repeated_page_noise(cleaned_pages, text_profile)
            cleaned_pages = [page for page in cleaned_pages if page.get("text")]
            cleaned_pages = self._annotate_page_offsets(cleaned_pages)
            content.pages = cleaned_pages
            content.text = "\n\n".join(page["text"] for page in cleaned_pages)
        else:
            content.text = self._clean_text_value(content.text, text_profile)

        if content.blocks is not None:
            block_profile = TextCleaningProfile(
                preserve_line_breaks=True,
                merge_paragraph_lines=False,
                preserve_indentation=False,
                deduplicate_consecutive_lines=False,
            )
            content.blocks = self._clean_content_blocks(content.blocks, block_profile)
            if content.blocks and content.pages is None:
                content.text = "\n\n".join(block["text"] for block in content.blocks if block.get("text"))

        if content.tables is not None:
            table_profile = TextCleaningProfile(
                preserve_line_breaks=True,
                merge_paragraph_lines=False,
                preserve_indentation=False,
                deduplicate_consecutive_lines=False,
            )
            content.tables = self._clean_nested_value(content.tables, table_profile)

        if content.images is not None:
            content.images = self._clean_nested_value(content.images, metadata_profile)

        if "char_count" in content.metadata:
            content.metadata["char_count"] = len(content.text)
        if "line_count" in content.metadata:
            content.metadata["line_count"] = len(content.text.splitlines()) if content.text else 0

        return content

    def _get_text_cleaning_profile(self, file_extension: str) -> TextCleaningProfile:
        normalized_extension = (file_extension or "").lower()
        if normalized_extension in self._STRUCTURED_EXTENSIONS:
            return TextCleaningProfile(
                preserve_line_breaks=True,
                merge_paragraph_lines=False,
                preserve_indentation=True,
                deduplicate_consecutive_lines=False,
            )
        if normalized_extension in self._MARKUP_EXTENSIONS:
            return TextCleaningProfile(
                preserve_line_breaks=True,
                merge_paragraph_lines=False,
                preserve_indentation=False,
                deduplicate_consecutive_lines=False,
            )
        return TextCleaningProfile(
            preserve_line_breaks=False,
            merge_paragraph_lines=True,
            preserve_indentation=False,
            deduplicate_consecutive_lines=True,
        )

    def _clean_nested_value(self, value: Any, profile: TextCleaningProfile) -> Any:
        if isinstance(value, dict):
            return {key: self._clean_nested_value(item, profile) for key, item in value.items()}
        if isinstance(value, list):
            return [self._clean_nested_value(item, profile) for item in value]
        if isinstance(value, tuple):
            return tuple(self._clean_nested_value(item, profile) for item in value)
        if isinstance(value, (str, bytes)):
            return self._clean_text_value(value, profile)
        return value

    def _clean_text_value(self, value: Any, profile: TextCleaningProfile) -> str:
        if value is None:
            return ""

        if isinstance(value, bytes):
            text = value.decode("utf-8", errors="replace")
        else:
            text = str(value)

        text = unicodedata.normalize("NFKC", text)
        text = text.replace("\ufeff", "").replace("\u00ad", "")
        text = re.sub(r"[\u200b-\u200f\u2060]", "", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\u00a0", " ").replace("\u3000", " ")
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

        lines = text.split("\n")
        cleaned_lines: List[str] = []
        for line in lines:
            cleaned_line = self._normalize_line(line, profile)
            if cleaned_line == "" and cleaned_lines and cleaned_lines[-1] == "":
                continue
            cleaned_lines.append(cleaned_line)

        if profile.deduplicate_consecutive_lines:
            cleaned_lines = self._deduplicate_consecutive_lines(cleaned_lines)
        if profile.merge_paragraph_lines and not profile.preserve_line_breaks:
            cleaned_lines = self._merge_broken_lines(cleaned_lines)

        text = "\n".join(cleaned_lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        return text.strip()

    def _normalize_line(self, line: str, profile: TextCleaningProfile) -> str:
        if profile.preserve_indentation:
            expanded = line.expandtabs(4).rstrip()
            prefix_length = len(expanded) - len(expanded.lstrip(" "))
            prefix = expanded[:prefix_length]
            body = re.sub(r"[ \t]{2,}", " ", expanded[prefix_length:]).rstrip()
            return prefix + body

        collapsed = line.replace("\t", " ")
        collapsed = re.sub(r"[ \t]+", " ", collapsed)
        return collapsed.strip()

    def _deduplicate_consecutive_lines(self, lines: List[str]) -> List[str]:
        deduplicated: List[str] = []
        for line in lines:
            if line and deduplicated and deduplicated[-1] == line and len(line) >= 3:
                continue
            deduplicated.append(line)
        return deduplicated

    def _clean_content_blocks(
        self,
        blocks: List[Dict[str, Any]],
        profile: TextCleaningProfile,
    ) -> List[Dict[str, Any]]:
        """清洗结构化块，并重新计算块内全局字符偏移。"""
        cleaned_blocks: List[Dict[str, Any]] = []
        current_start = 0
        for block in blocks or []:
            if not isinstance(block, dict):
                continue

            cleaned_block = self._clean_nested_value(dict(block), profile)
            cleaned_text = str(cleaned_block.get("text") or "").strip()
            if not cleaned_text:
                continue

            cleaned_block["text"] = cleaned_text
            cleaned_block["start"] = current_start
            cleaned_block["char_count"] = len(cleaned_text)
            cleaned_blocks.append(cleaned_block)
            current_start += len(cleaned_text) + 2
        return cleaned_blocks

    def _annotate_page_offsets(self, pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """为页级内容补充全局字符偏移，供 PDF 分块直接复用。"""
        annotated_pages: List[Dict[str, Any]] = []
        current_start = 0
        for page in pages or []:
            if not isinstance(page, dict):
                continue
            page_text = str(page.get("text") or "")
            annotated_page = dict(page)
            annotated_page["start_char"] = current_start
            annotated_page["end_char"] = current_start + len(page_text)
            annotated_pages.append(annotated_page)
            current_start = annotated_page["end_char"] + 2
        return annotated_pages

    def _merge_broken_lines(self, lines: List[str]) -> List[str]:
        merged: List[str] = []
        buffer = ""

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if buffer:
                    merged.append(buffer.strip())
                    buffer = ""
                if merged and merged[-1] != "":
                    merged.append("")
                continue

            if not buffer:
                buffer = stripped
                continue

            if self._should_merge_lines(buffer, stripped):
                buffer = self._merge_line_pair(buffer, stripped)
            else:
                merged.append(buffer.strip())
                buffer = stripped

        if buffer:
            merged.append(buffer.strip())

        while merged and merged[-1] == "":
            merged.pop()
        return merged

    def _should_merge_lines(self, previous_line: str, current_line: str) -> bool:
        if not previous_line or not current_line:
            return False
        if self._is_structural_line(previous_line) or self._is_structural_line(current_line):
            return False
        if re.search(r"[.!?。！？；;:：]$", previous_line):
            return False
        if self._looks_like_heading(previous_line):
            return False
        if re.search(r"[-‐‑]$", previous_line):
            return bool(re.match(r"^[A-Za-z0-9]", current_line))
        if previous_line.endswith((",", "，", "、", "/", "／", "(", "（")):
            return True
        if current_line[0] in "),，。；;:：!?！？」』】）)]":
            return True
        if re.match(r"^[a-z]", current_line):
            return True
        if re.match(r'^[\u4e00-\u9fff\u201c"\u2018\uff08(]', current_line):
            return True
        return len(previous_line) < 90 and not self._looks_like_heading(current_line)

    def _merge_line_pair(self, previous_line: str, current_line: str) -> str:
        if re.search(r"[-‐‑]$", previous_line) and re.match(r"^[A-Za-z0-9]", current_line):
            return previous_line[:-1] + current_line.lstrip()
        if previous_line.endswith(("(", "（", "/", "／")):
            return previous_line + current_line.lstrip()
        if current_line[0] in "),，。；;:：!?！？」』】）)]":
            return previous_line + current_line.lstrip()
        return f"{previous_line} {current_line}".strip()

    def _is_structural_line(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        return (
            bool(self._BULLET_LINE_RE.match(stripped))
            or self._looks_like_table_row(stripped)
            or self._looks_like_heading(stripped)
        )

    def _looks_like_table_row(self, line: str) -> bool:
        if "|" in line or "\t" in line:
            return True
        return bool(re.search(r"\S+\s{2,}\S+", line))

    def _looks_like_heading(self, line: str) -> bool:
        # 常见编号标题需要在清洗阶段被识别出来，避免与下一行正文误合并。
        if len(line) > 60:
            return False
        if re.search(r"[.!?。！？；;:：]$", line):
            return False
        if re.match(r"^(?:chapter|section|appendix)\b", line, re.IGNORECASE):
            return True
        if re.match(r"^\d+(?:\.\d+){0,5}\s+\S+", line):
            return True
        if re.match(r"^第[一二三四五六七八九十0-9]+(?:章|节|部分|条)", line):
            return True
        if re.match(r"^[A-Z0-9][A-Z0-9 _./:-]{2,}$", line):
            return True
        return False

    def _strip_repeated_page_noise(
        self,
        pages: List[Dict[str, Any]],
        profile: TextCleaningProfile,
    ) -> List[Dict[str, Any]]:
        line_sets: List[List[str]] = []
        for page in pages:
            lines = [line.strip() for line in str(page.get("text", "")).split("\n") if line.strip()]
            line_sets.append(lines)

        non_empty_line_sets = [lines for lines in line_sets if lines]
        if len(non_empty_line_sets) < 2:
            return pages

        threshold = max(2, (len(non_empty_line_sets) * 3 + 4) // 5)
        header_counter = Counter(self._normalize_repeated_page_line(lines[0]) for lines in non_empty_line_sets)
        footer_counter = Counter(self._normalize_repeated_page_line(lines[-1]) for lines in non_empty_line_sets)

        repeated_headers = {
            line
            for line, count in header_counter.items()
            if line and count >= threshold and self._is_repeated_page_noise_line(line)
        }
        repeated_footers = {
            line
            for line, count in footer_counter.items()
            if line and count >= threshold and self._is_repeated_page_noise_line(line)
        }

        cleaned_pages: List[Dict[str, Any]] = []
        for page, lines in zip(pages, line_sets):
            working_lines = list(lines)

            while working_lines and (
                self._is_page_noise_line(working_lines[0])
                or self._normalize_repeated_page_line(working_lines[0]) in repeated_headers
            ):
                working_lines.pop(0)

            while working_lines and (
                self._is_page_noise_line(working_lines[-1])
                or self._normalize_repeated_page_line(working_lines[-1]) in repeated_footers
            ):
                working_lines.pop()

            cleaned_page = dict(page)
            cleaned_page["text"] = self._clean_text_value("\n".join(working_lines), profile)
            cleaned_page["char_count"] = len(cleaned_page["text"])
            cleaned_pages.append(cleaned_page)

        return cleaned_pages

    def _is_repeated_page_noise_line(self, line: str) -> bool:
        normalized = re.sub(r"\s+", " ", str(line or "")).strip()
        if not normalized or len(normalized) > 80:
            return False
        if self._is_page_noise_line(normalized):
            return True
        # 对论文标题、法规标题等真实页眉保持克制，避免仅因“重复出现”就误删正文语义线索。
        if self._looks_like_heading(normalized):
            return False
        if self._looks_like_table_row(normalized) or self._BULLET_LINE_RE.match(normalized):
            return False
        return not bool(re.search(r"[.!?;:]$", normalized))

    def _normalize_repeated_page_line(self, line: str) -> str:
        normalized = self._clean_text_value(
            line,
            TextCleaningProfile(
                preserve_line_breaks=True,
                merge_paragraph_lines=False,
                preserve_indentation=False,
            ),
        )
        return re.sub(r"\s+", " ", normalized).strip().lower()

    def _is_page_noise_line(self, line: str) -> bool:
        normalized = re.sub(r"\s+", " ", str(line or "")).strip()
        if not normalized or len(normalized) > 80:
            return False
        return any(pattern.match(normalized) for pattern in self._PAGE_NUMBER_PATTERNS)

    def extract_metadata(self, file_path: str) -> Dict[str, Any]:
        try:
            stat = os.stat(file_path)
            filename = os.path.basename(file_path)
            file_ext = os.path.splitext(filename)[1].lower()

            return {
                "filename": filename,
                "file_extension": file_ext,
                "file_size": stat.st_size,
                "created_time": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        except Exception as exc:
            self.logger.warning(f"Failed to extract metadata: {str(exc)}")
            return {}

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"
