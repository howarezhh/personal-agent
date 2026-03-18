from __future__ import annotations

from dataclasses import replace
import re
from typing import Any, Dict, Iterable, List, Optional
import uuid

from backend.file_processors.parsers.base_parser import ParsedContent
from backend.models.file import FileChunk, FileType


class DocumentChunker:
    _MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    _CODE_SYMBOL_RE = re.compile(
        r"^(?:\s*(?:async\s+)?def\s+(?P<py_func>[A-Za-z_][\w]*)\s*\(|"
        r"\s*class\s+(?P<py_class>[A-Za-z_][\w]*)\s*(?:\(|:)|"
        r"\s*function\s+(?P<js_func>[A-Za-z_$][\w$]*)\s*\(|"
        r"\s*(?:export\s+)?class\s+(?P<js_class>[A-Za-z_$][\w$]*)\s*|"
        r"\s*(?P<go_func>func)\s+(?P<go_name>[A-Za-z_][\w]*)\s*\(|"
        r"\s*(?:public|private|protected)?\s*(?:static\s+)?(?:class|interface)\s+(?P<java_type>[A-Za-z_][\w]*)\s*|"
        r"\s*(?:public|private|protected)?\s*(?:static\s+)?[\w<>\[\]]+\s+(?P<java_method>[A-Za-z_][\w]*)\s*\()"
    )
    _STRUCTURED_KEY_RE = re.compile(r'^\s*["\']?(?P<key>[A-Za-z0-9_.-]+)["\']?\s*:\s*')
    _XML_TAG_RE = re.compile(r"<([A-Za-z][\w:-]*)\b")

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 100, max_chunk_tokens: Optional[int] = None):
        self.chunk_size = max(1, int(chunk_size))
        self.chunk_overlap = max(0, min(int(chunk_overlap), self.chunk_size - 1))
        self.max_chunk_tokens = max(1, int(max_chunk_tokens)) if max_chunk_tokens else None

    def chunk_parsed_content(self, parsed_content: ParsedContent, metadata: Dict[str, Any]) -> List[FileChunk]:
        base_metadata = dict(metadata or {})
        file_type = self._normalize_file_type(base_metadata.get("file_type"))

        if file_type == FileType.XLSX.value and parsed_content.tables:
            return self._chunk_excel_tables(parsed_content.tables, base_metadata)

        if file_type == FileType.PDF.value and parsed_content.pages:
            return self._chunk_pdf_pages(parsed_content.pages, base_metadata)

        if file_type in {FileType.MARKDOWN.value, FileType.HTML.value}:
            return self._chunk_markdown_like(parsed_content.text, base_metadata)

        if file_type == FileType.DOCX.value:
            return self._chunk_docx_content(parsed_content, base_metadata)

        if file_type == FileType.CODE.value:
            return self._chunk_code_content(parsed_content.text, base_metadata)

        if file_type in {FileType.JSON.value, FileType.XML.value} or self._looks_like_structured_text(parsed_content.text):
            return self._chunk_structured_text(parsed_content.text, base_metadata)

        if parsed_content.pages:
            return self.chunk_with_pages(parsed_content.pages, base_metadata)

        return self.chunk_text(parsed_content.text, base_metadata)

    def chunk_text(self, text: str, metadata: Dict[str, Any]) -> List[FileChunk]:
        normalized_text = str(text or "")
        if not normalized_text:
            return []
        return self._create_text_chunks(normalized_text, dict(metadata or {}), 0)

    def chunk_with_pages(self, pages: Iterable[Dict[str, Any]], base_metadata: Dict[str, Any]) -> List[FileChunk]:
        chunks: List[FileChunk] = []
        chunk_index = 0
        for page in pages or []:
            if not isinstance(page, dict):
                continue
            page_number = page.get("page_number")
            page_text = str(page.get("text") or "")
            page_metadata = dict(base_metadata or {})
            page_metadata["page_number"] = page_number
            page_chunks = self.chunk_text(page_text, page_metadata)
            for page_chunk in page_chunks:
                chunks.append(
                    replace(
                        page_chunk,
                        chunk_index=chunk_index,
                        page_number=page_number,
                        metadata={**(page_chunk.metadata or {}), "page_number": page_number},
                    )
                )
                chunk_index += 1
        return chunks

    def _chunk_pdf_pages(self, pages: Iterable[Dict[str, Any]], base_metadata: Dict[str, Any]) -> List[FileChunk]:
        chunks: List[FileChunk] = []
        chunk_index = 0
        for page in pages or []:
            if not isinstance(page, dict):
                continue
            page_number = page.get("page_number")
            page_text = str(page.get("text") or "")
            page_chunks = self._split_text_into_blocks(page_text, strategy="paragraph")
            page_offset = 0
            for block in page_chunks:
                block_metadata = dict(base_metadata or {})
                block_metadata.update(
                    {
                        "page_number": page_number,
                        "section_title": self._derive_section_title(block),
                        "section_path": self._derive_section_title(block),
                    }
                )
                for chunk in self._create_text_chunks(block, block_metadata, chunk_index, start_offset=page_offset):
                    chunks.append(replace(chunk, page_number=page_number))
                    chunk_index += 1
                page_offset += len(block) + 2
        return chunks

    def _chunk_markdown_like(self, text: str, base_metadata: Dict[str, Any]) -> List[FileChunk]:
        normalized_text = str(text or "")
        if not normalized_text:
            return []

        lines = normalized_text.splitlines(keepends=True)
        sections: List[Dict[str, Any]] = []
        heading_stack: List[Dict[str, Any]] = []
        current_lines: List[str] = []
        current_start = 0
        position = 0

        def flush() -> None:
            if not current_lines:
                return
            block_text = "".join(current_lines).strip()
            if not block_text:
                return
            section_title = heading_stack[-1]["title"] if heading_stack else self._derive_section_title(block_text)
            section_path = " / ".join(item["title"] for item in heading_stack) or section_title
            heading_level = heading_stack[-1]["level"] if heading_stack else None
            sections.append(
                {
                    "text": block_text,
                    "start": current_start,
                    "section_title": section_title,
                    "section_path": section_path,
                    "heading_level": heading_level,
                }
            )

        for line in lines:
            heading_match = self._MARKDOWN_HEADING_RE.match(line.strip())
            if heading_match:
                flush()
                current_lines = [line]
                current_start = position
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                heading_stack = [item for item in heading_stack if item["level"] < level]
                heading_stack.append({"level": level, "title": title})
            else:
                if not current_lines:
                    current_start = position
                current_lines.append(line)
            position += len(line)

        flush()
        return self._materialize_blocks(sections, base_metadata)

    def _chunk_docx_content(self, parsed_content: ParsedContent, base_metadata: Dict[str, Any]) -> List[FileChunk]:
        blocks: List[Dict[str, Any]] = []
        position = 0
        for paragraph in self._split_text_into_blocks(parsed_content.text, strategy="paragraph"):
            blocks.append(
                {
                    "text": paragraph,
                    "start": position,
                    "section_title": self._derive_section_title(paragraph),
                    "section_path": self._derive_section_title(paragraph),
                    "heading_level": 1 if self._looks_like_heading(paragraph) else None,
                }
            )
            position += len(paragraph) + 2

        for table_index, table in enumerate(parsed_content.tables or [], start=1):
            table_lines = []
            if isinstance(table, dict):
                for row in table.get("rows", []):
                    if isinstance(row, list):
                        row_text = " | ".join(str(cell or "").strip() for cell in row if str(cell or "").strip())
                        if row_text:
                            table_lines.append(row_text)
            table_text = "\n".join(table_lines).strip()
            if table_text:
                blocks.append(
                    {
                        "text": table_text,
                        "start": position,
                        "section_title": f"table_{table_index}",
                        "section_path": f"table_{table_index}",
                        "heading_level": None,
                        "table_index": table_index,
                    }
                )
                position += len(table_text) + 2

        return self._materialize_blocks(blocks, base_metadata)

    def _chunk_code_content(self, text: str, base_metadata: Dict[str, Any]) -> List[FileChunk]:
        normalized_text = str(text or "")
        if not normalized_text:
            return []

        lines = normalized_text.splitlines(keepends=True)
        blocks: List[Dict[str, Any]] = []
        current_lines: List[str] = []
        current_start = 0
        current_symbol: Optional[str] = None
        current_symbol_type: Optional[str] = None
        position = 0

        def flush() -> None:
            if not current_lines:
                return
            block_text = "".join(current_lines).strip()
            if not block_text:
                return
            blocks.append(
                {
                    "text": block_text,
                    "start": current_start,
                    "section_title": current_symbol or self._derive_section_title(block_text),
                    "section_path": current_symbol or self._derive_section_title(block_text),
                    "symbol_name": current_symbol,
                    "symbol_type": current_symbol_type,
                }
            )

        for line in lines:
            symbol_match = self._CODE_SYMBOL_RE.match(line)
            if symbol_match:
                flush()
                current_lines = [line]
                current_start = position
                current_symbol, current_symbol_type = self._extract_code_symbol(symbol_match.groupdict())
            else:
                if not current_lines:
                    current_start = position
                current_lines.append(line)
            position += len(line)

        flush()
        return self._materialize_blocks(blocks, base_metadata)

    def _chunk_structured_text(self, text: str, base_metadata: Dict[str, Any]) -> List[FileChunk]:
        normalized_text = str(text or "")
        if not normalized_text:
            return []

        blocks: List[Dict[str, Any]] = []
        current_lines: List[str] = []
        current_start = 0
        current_path: Optional[str] = None
        position = 0
        lines = normalized_text.splitlines(keepends=True)

        def flush() -> None:
            if not current_lines:
                return
            block_text = "".join(current_lines).strip()
            if not block_text:
                return
            blocks.append(
                {
                    "text": block_text,
                    "start": current_start,
                    "section_title": current_path or self._derive_section_title(block_text),
                    "section_path": current_path or self._derive_section_title(block_text),
                    "node_name": current_path.split(".")[-1] if current_path else None,
                    "leaf_value": self._extract_leaf_value(block_text),
                }
            )

        for line in lines:
            key_match = self._STRUCTURED_KEY_RE.match(line)
            xml_match = self._XML_TAG_RE.search(line)
            path_value = key_match.group("key") if key_match else (xml_match.group(1) if xml_match else None)
            if path_value and current_lines:
                flush()
                current_lines = [line]
                current_start = position
                current_path = path_value
            else:
                if not current_lines:
                    current_start = position
                    current_path = path_value or current_path
                current_lines.append(line)
            position += len(line)

        flush()
        return self._materialize_blocks(blocks, base_metadata)

    def _chunk_excel_tables(self, tables: Iterable[Dict[str, Any]], base_metadata: Dict[str, Any]) -> List[FileChunk]:
        chunks: List[FileChunk] = []
        chunk_index = 0
        for table_index, table in enumerate(tables or [], start=1):
            if not isinstance(table, dict):
                continue
            sheet_name = str(table.get("sheet_name") or f"sheet_{table_index}")
            columns = [str(column or "").strip() for column in table.get("columns", [])]
            rows = table.get("rows", [])
            row_group: List[List[str]] = []
            row_group_start = 0
            for row_offset, row in enumerate(rows or [], start=1):
                if isinstance(row, list):
                    row_group.append([str(cell or "").strip() for cell in row])
                if len(row_group) >= 20:
                    content = self._build_excel_chunk_text(sheet_name, columns, row_group, row_group_start + 1)
                    metadata = dict(base_metadata or {})
                    metadata.update(
                        {
                            "sheet_name": sheet_name,
                            "table_index": table_index,
                            "section_title": sheet_name,
                            "section_path": sheet_name,
                            "column_headers": columns,
                        }
                    )
                    for chunk in self._create_text_chunks(content, metadata, chunk_index):
                        chunks.append(chunk)
                        chunk_index += 1
                    row_group = []
                    row_group_start = row_offset

            if row_group:
                content = self._build_excel_chunk_text(sheet_name, columns, row_group, row_group_start + 1)
                metadata = dict(base_metadata or {})
                metadata.update(
                    {
                        "sheet_name": sheet_name,
                        "table_index": table_index,
                        "section_title": sheet_name,
                        "section_path": sheet_name,
                        "column_headers": columns,
                    }
                )
                for chunk in self._create_text_chunks(content, metadata, chunk_index):
                    chunks.append(chunk)
                    chunk_index += 1

        return chunks

    def _materialize_blocks(self, blocks: List[Dict[str, Any]], base_metadata: Dict[str, Any]) -> List[FileChunk]:
        chunks: List[FileChunk] = []
        chunk_index = 0
        for block in blocks:
            metadata = dict(base_metadata or {})
            metadata.update(
                {
                    "section_title": block.get("section_title"),
                    "section_path": block.get("section_path"),
                    "heading_level": block.get("heading_level"),
                }
            )
            if block.get("table_index") is not None:
                metadata["table_index"] = block.get("table_index")
            for key in ("symbol_name", "symbol_type", "node_name", "leaf_value", "column_headers"):
                if block.get(key) is not None:
                    metadata[key] = block.get(key)
            for chunk in self._create_text_chunks(
                block.get("text") or "",
                metadata,
                chunk_index,
                start_offset=int(block.get("start") or 0),
            ):
                chunks.append(chunk)
                chunk_index += 1
        return chunks

    def _create_text_chunks(
        self,
        text: str,
        metadata: Dict[str, Any],
        chunk_index_start: int,
        start_offset: int = 0,
    ) -> List[FileChunk]:
        normalized_text = str(text or "")
        if not normalized_text:
            return []

        file_id = str((metadata or {}).get("file_id") or "")
        chunks: List[FileChunk] = []
        start = 0
        chunk_index = chunk_index_start
        while start < len(normalized_text):
            end = min(len(normalized_text), start + self.chunk_size)
            end = self._fit_chunk_end_by_token_budget(normalized_text, start, end)
            content = normalized_text[start:end].strip()
            if content:
                absolute_start = start_offset + start
                absolute_end = start_offset + end
                chunk_metadata = self._build_chunk_metadata(metadata, absolute_start, absolute_end, content)
                chunks.append(
                    FileChunk(
                        chunk_id=str(uuid.uuid4()),
                        file_id=file_id,
                        chunk_index=chunk_index,
                        content=content,
                        page_number=chunk_metadata.get("page_number"),
                        start_char=absolute_start,
                        end_char=absolute_end,
                        token_count=chunk_metadata["token_count"],
                        metadata=chunk_metadata,
                    )
                )
                chunk_index += 1
            if end >= len(normalized_text):
                break
            start = max(end - self.chunk_overlap, start + 1)
        return chunks

    def _fit_chunk_end_by_token_budget(self, text: str, start: int, end: int) -> int:
        if self.max_chunk_tokens is None:
            return end

        if start >= end:
            return end

        candidate = text[start:end].strip()
        if not candidate:
            return end

        if self._estimate_token_count(candidate) <= self.max_chunk_tokens:
            return end

        low = start + 1
        high = end
        best = low
        while low <= high:
            mid = (low + high) // 2
            sample = text[start:mid].strip()
            if not sample:
                low = mid + 1
                continue
            if self._estimate_token_count(sample) <= self.max_chunk_tokens:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        return max(start + 1, best)

    def _build_chunk_metadata(self, metadata: Dict[str, Any], start_char: int, end_char: int, content: str) -> Dict[str, Any]:
        chunk_metadata = dict(metadata or {})
        chunk_metadata["start_char"] = start_char
        chunk_metadata["end_char"] = end_char
        chunk_metadata["token_count"] = self._estimate_token_count(content)
        chunk_metadata.setdefault("section_title", None)
        chunk_metadata.setdefault("section_path", None)
        chunk_metadata.setdefault("heading_level", None)
        chunk_metadata.setdefault("sheet_name", None)
        chunk_metadata.setdefault("table_index", None)
        chunk_metadata.setdefault("symbol_name", None)
        chunk_metadata.setdefault("symbol_type", None)
        chunk_metadata.setdefault("node_name", None)
        chunk_metadata.setdefault("leaf_value", None)
        chunk_metadata.setdefault("column_headers", None)
        return chunk_metadata

    def _extract_code_symbol(self, group_dict: Dict[str, Optional[str]]) -> tuple[Optional[str], Optional[str]]:
        symbol_type_map = {
            "py_func": "function",
            "py_class": "class",
            "js_func": "function",
            "js_class": "class",
            "go_name": "function",
            "java_type": "class",
            "java_method": "function",
        }
        for key, symbol_type in symbol_type_map.items():
            value = group_dict.get(key)
            if value:
                return value, symbol_type
        return None, None

    def _extract_leaf_value(self, text: str) -> Optional[str]:
        for line in str(text or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            key_match = self._STRUCTURED_KEY_RE.match(stripped)
            if key_match:
                remainder = stripped[key_match.end() :].strip().strip(',')
                if remainder and remainder not in {"{", "["}:
                    return remainder[:120]
            xml_match = re.search(r">([^<]+)<", stripped)
            if xml_match:
                leaf = xml_match.group(1).strip()
                if leaf:
                    return leaf[:120]
        return None

    def _split_text_into_blocks(self, text: str, strategy: str = "paragraph") -> List[str]:
        normalized_text = str(text or "").strip()
        if not normalized_text:
            return []
        if strategy == "paragraph":
            blocks = [block.strip() for block in re.split(r"\n\s*\n+", normalized_text) if block.strip()]
            return blocks or [normalized_text]
        return [normalized_text]

    def _build_excel_chunk_text(
        self,
        sheet_name: str,
        columns: List[str],
        row_group: List[List[str]],
        start_row: int,
    ) -> str:
        lines = [f"[{sheet_name}]", f"columns: {' | '.join(column for column in columns if column)}"]
        for offset, row in enumerate(row_group, start=start_row):
            values = [f"{column}: {value}" for column, value in zip(columns, row) if value]
            if values:
                lines.append(f"row {offset}: " + " | ".join(values))
        return "\n".join(lines)

    def _derive_section_title(self, text: str) -> Optional[str]:
        for line in str(text or "").splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                return stripped[:120]
        return None

    def _looks_like_heading(self, text: str) -> bool:
        first_line = str(text or "").splitlines()[0].strip() if str(text or "").splitlines() else ""
        if not first_line:
            return False
        return len(first_line) <= 80 and not re.search(r"[.!?。；;:]$", first_line)

    def _looks_like_structured_text(self, text: str) -> bool:
        sample = str(text or "")[:500]
        return bool(self._STRUCTURED_KEY_RE.search(sample) or self._XML_TAG_RE.search(sample))

    def _normalize_file_type(self, file_type: Any) -> str:
        if isinstance(file_type, FileType):
            return file_type.value
        return str(file_type or "").lower()

    @staticmethod
    def _estimate_token_count(text: str) -> int:
        stripped = str(text or "").strip()
        if not stripped:
            return 0
        return max(1, len(stripped.split())) if " " in stripped else max(1, len(stripped) // 2)
