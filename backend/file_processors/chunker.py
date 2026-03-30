from __future__ import annotations

from dataclasses import replace
import json
import re
from typing import Any, Callable, Dict, Iterable, List, Optional
import uuid
import xml.etree.ElementTree as ET

from backend.file_processors.parsers.base_parser import ParsedContent
from backend.models.file import FileChunk, FileType


class DocumentChunker:
    _MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    _RST_HEADING_UNDERLINE_RE = re.compile(r'^(?P<char>[=\-~`:#"\'^_*+])\1{2,}\s*$')
    _STRUCTURED_TEXT_EXTENSIONS = {".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env", ".properties"}
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
    _DEFAULT_TOKENIZER_NAME = "cl100k_base"

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 100,
        max_chunk_tokens: Optional[int] = None,
        token_counter: Optional[Callable[[str], int]] = None,
    ):
        # `chunk_size`：单块的目标字符长度上限，用于决定首次切块窗口。
        self.chunk_size = max(1, int(chunk_size))
        # `chunk_overlap`：块间重叠范围，后续会尽量对齐到句子或段落边界。
        self.chunk_overlap = max(0, min(int(chunk_overlap), self.chunk_size - 1))
        # `max_chunk_tokens`：向量模型单块 token 预算，用于二次精确控长。
        self.max_chunk_tokens = max(1, int(max_chunk_tokens)) if max_chunk_tokens else None
        # `token_counter`：优先使用注入的 tokenizer；未注入时尽量加载真实 tokenizer，再最后兜底。
        self.token_counter = token_counter or self._build_default_token_counter()

    def chunk_parsed_content(self, parsed_content: ParsedContent, metadata: Dict[str, Any]) -> List[FileChunk]:
        base_metadata = dict(metadata or {})
        file_type = self._normalize_file_type(base_metadata.get("file_type"))
        file_extension = str(base_metadata.get("file_extension") or "").lower()
        if not file_extension:
            filename = str(base_metadata.get("filename") or "")
            if filename:
                match = re.search(r"(\.[^.\\/]+)$", filename)
                file_extension = match.group(1).lower() if match else ""

        if file_type in {FileType.XLSX.value, FileType.TABULAR.value} and parsed_content.tables:
            return self._chunk_excel_tables(parsed_content.tables, base_metadata)

        if file_type == FileType.PDF.value and parsed_content.pages:
            return self._chunk_pdf_pages(parsed_content.pages, base_metadata)

        # HTML 解析器若已提供结构化块，则优先复用结构，避免只按纯文本再次粗切。
        if file_type == FileType.HTML.value and parsed_content.blocks:
            return self._materialize_blocks([dict(block) for block in parsed_content.blocks if isinstance(block, dict)], base_metadata)

        if file_type in {FileType.MARKDOWN.value, FileType.HTML.value}:
            return self._chunk_markdown_like(parsed_content.text, base_metadata)

        if file_type == FileType.DOCX.value:
            return self._chunk_docx_content(parsed_content, base_metadata)

        if file_extension == ".rst":
            return self._chunk_rst_like(parsed_content.text, base_metadata)

        if file_extension in self._STRUCTURED_TEXT_EXTENSIONS:
            if file_extension in {".yaml", ".yml"}:
                return self._chunk_yaml_like(parsed_content.text, base_metadata)
            if file_extension in {".toml", ".ini", ".cfg", ".conf", ".env", ".properties"}:
                return self._chunk_key_value_config(parsed_content.text, base_metadata, file_extension=file_extension)
            return self._chunk_structured_text(parsed_content.text, base_metadata)

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
            # 中文说明：除正文外尽量保留分页结构元数据，避免 PPT/PDF 的页标题、OCR 标记在切块时丢失。
            for key, value in page.items():
                if key in {"text", "char_count"}:
                    continue
                page_metadata[key] = value
            page_metadata["page_number"] = page_number
            page_start_offset = int(page.get("start_char") or 0)
            page_chunks = self._create_text_chunks(page_text, page_metadata, chunk_index, start_offset=page_start_offset)
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
        carry_section_title: Optional[str] = None
        for page in pages or []:
            if not isinstance(page, dict):
                continue
            page_number = page.get("page_number")
            page_text = str(page.get("text") or "")
            # PDF 先尝试按标题/列表/段落识别逻辑块，识别失败时再回退纯段落。
            page_chunks = self._extract_pdf_blocks(page_text)
            page_offset = int(page.get("start_char") or 0)
            block_offset = 0
            current_section_title: Optional[str] = carry_section_title
            for block in page_chunks:
                if self._looks_like_heading(block):
                    current_section_title = self._derive_section_title(block)
                block_metadata = dict(base_metadata or {})
                block_metadata.update(
                    {
                        "page_number": page_number,
                        "section_title": current_section_title or self._derive_section_title(block),
                        "section_path": current_section_title or self._derive_section_title(block),
                        "page_start_char": page_offset,
                        "ocr_applied": page.get("ocr_applied"),
                        "text_source": page.get("text_source"),
                    }
                )
                for chunk in self._create_text_chunks(block, block_metadata, chunk_index, start_offset=page_offset + block_offset):
                    chunks.append(replace(chunk, page_number=page_number))
                    chunk_index += 1
                block_offset += len(block) + 2
            carry_section_title = current_section_title
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

    def _chunk_rst_like(self, text: str, base_metadata: Dict[str, Any]) -> List[FileChunk]:
        """按 RST 标题下划线语法做结构化切分，避免 `.rst` 被当成纯文本。"""
        normalized_text = str(text or "")
        if not normalized_text:
            return []

        lines = normalized_text.splitlines(keepends=True)
        sections: List[Dict[str, Any]] = []
        heading_stack: List[Dict[str, Any]] = []
        current_lines: List[str] = []
        current_start = 0
        position = 0

        underline_to_level: Dict[str, int] = {}

        def resolve_heading_level(underline: str) -> int:
            underline_char = underline[:1]
            if underline_char not in underline_to_level:
                underline_to_level[underline_char] = len(underline_to_level) + 1
            return min(6, underline_to_level[underline_char])

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

        line_index = 0
        while line_index < len(lines):
            current_line = lines[line_index]
            next_line = lines[line_index + 1] if line_index + 1 < len(lines) else ""
            current_line_text = current_line.rstrip("\r\n")
            next_line_text = next_line.rstrip("\r\n")
            underline_match = self._RST_HEADING_UNDERLINE_RE.match(next_line_text.strip())

            if current_line_text.strip() and underline_match and len(next_line_text.strip()) >= len(current_line_text.strip()):
                flush()
                level = resolve_heading_level(next_line_text.strip())
                title = current_line_text.strip()
                heading_stack = [item for item in heading_stack if item["level"] < level]
                heading_stack.append({"level": level, "title": title})
                heading_block = f"{'#' * level} {title}"
                sections.append(
                    {
                        "text": heading_block,
                        "start": position,
                        "section_title": title,
                        "section_path": " / ".join(item["title"] for item in heading_stack),
                        "heading_level": level,
                    }
                )
                current_lines = []
                current_start = position + len(current_line) + len(next_line)
                position += len(current_line) + len(next_line)
                line_index += 2
                continue

            if not current_lines:
                current_start = position
            current_lines.append(current_line)
            position += len(current_line)
            line_index += 1

        flush()
        return self._materialize_blocks(sections, base_metadata)

    def _chunk_docx_content(self, parsed_content: ParsedContent, base_metadata: Dict[str, Any]) -> List[FileChunk]:
        raw_blocks = [dict(block) for block in (parsed_content.blocks or []) if isinstance(block, dict) and block.get("text")]
        if not raw_blocks:
            return self._chunk_markdown_like(parsed_content.text, base_metadata)

        docx_blocks: List[Dict[str, Any]] = []
        current_group: Optional[Dict[str, Any]] = None

        def flush_current_group() -> None:
            nonlocal current_group
            if current_group and current_group.get("text"):
                docx_blocks.append(current_group)
            current_group = None

        for block in raw_blocks:
            block_type = str(block.get("block_type") or "paragraph")
            block_text = str(block.get("text") or "").strip()
            if not block_text:
                continue

            if block_type == "table":
                flush_current_group()
                docx_blocks.append(
                    {
                        "block_type": "table",
                        "text": block_text,
                        "start": int(block.get("start") or 0),
                        "section_title": block.get("section_title") or self._derive_section_title(block_text),
                        "section_path": block.get("section_path") or self._derive_section_title(block_text),
                        "heading_level": block.get("heading_level"),
                        "table_index": block.get("table_index"),
                        "column_headers": block.get("column_headers"),
                        "source_region": block.get("source_region"),
                    }
                )
                continue

            if block_type == "heading":
                flush_current_group()
                current_group = {
                    "block_type": "text",
                    "text": block_text,
                    "start": int(block.get("start") or 0),
                    "section_title": block.get("section_title") or self._derive_section_title(block_text),
                    "section_path": block.get("section_path") or self._derive_section_title(block_text),
                    "heading_level": block.get("heading_level"),
                    "source_region": block.get("source_region"),
                }
                continue

            if current_group is None:
                current_group = {
                    "block_type": "text",
                    "text": block_text,
                    "start": int(block.get("start") or 0),
                    "section_title": block.get("section_title") or self._derive_section_title(block_text),
                    "section_path": block.get("section_path") or self._derive_section_title(block_text),
                    "heading_level": block.get("heading_level"),
                    "source_region": block.get("source_region"),
                }
                continue

            # 不同来源区域（如页眉、正文、页脚）必须先拆开，避免后续块定位失真。
            if current_group.get("source_region") != block.get("source_region"):
                flush_current_group()
                current_group = {
                    "block_type": "text",
                    "text": block_text,
                    "start": int(block.get("start") or 0),
                    "section_title": block.get("section_title") or self._derive_section_title(block_text),
                    "section_path": block.get("section_path") or self._derive_section_title(block_text),
                    "heading_level": block.get("heading_level"),
                    "source_region": block.get("source_region"),
                }
                continue

            current_group["text"] = f"{current_group['text']}\n\n{block_text}"

        flush_current_group()
        merged_blocks = self._merge_small_docx_blocks(docx_blocks)
        return self._materialize_blocks(merged_blocks, base_metadata)

    def _merge_small_docx_blocks(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """按标题树对过短 DOCX 节点做最小块长合并。"""
        min_block_chars = max(120, min(400, self.chunk_size // 3))
        merged_blocks: List[Dict[str, Any]] = []
        index = 0

        while index < len(blocks):
            current_block = dict(blocks[index])
            current_text = str(current_block.get("text") or "")

            if current_block.get("block_type") == "table":
                merged_blocks.append(current_block)
                index += 1
                continue

            while (
                len(current_text) < min_block_chars
                and index + 1 < len(blocks)
                and blocks[index + 1].get("block_type") != "table"
                and self._docx_parent_path(current_block.get("section_path"))
                == self._docx_parent_path(blocks[index + 1].get("section_path"))
                # 不同来源区域（如页眉、正文、页脚）不能合并，否则会污染定位信息。
                and current_block.get("source_region") == blocks[index + 1].get("source_region")
            ):
                next_block = blocks[index + 1]
                current_text = f"{current_text}\n\n{str(next_block.get('text') or '').strip()}".strip()
                current_block["text"] = current_text
                # 保留首块的主章节路径，避免合并后引用错误地漂移到后一节。
                merged_paths = list(current_block.get("merged_section_paths") or [])
                next_path = next_block.get("section_path")
                if next_path and next_path not in merged_paths:
                    merged_paths.append(next_path)
                if merged_paths:
                    current_block["merged_section_paths"] = merged_paths
                index += 1

            merged_blocks.append(current_block)
            index += 1

        return merged_blocks

    @staticmethod
    def _docx_parent_path(section_path: Any) -> Optional[str]:
        normalized_path = str(section_path or "").strip()
        if not normalized_path:
            return None
        path_parts = [part.strip() for part in normalized_path.split("/") if part.strip()]
        if len(path_parts) <= 1:
            return normalized_path
        return " / ".join(path_parts[:-1])

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
        current_section_path: Optional[str] = None
        position = 0
        brace_depth = 0
        container_stack: List[Dict[str, Any]] = []

        def current_container_path() -> Optional[str]:
            container_names = [str(item.get("name") or "").strip() for item in container_stack if str(item.get("name") or "").strip()]
            return " / ".join(container_names) if container_names else None

        def pop_inactive_containers(indent: int, stripped_line: str) -> None:
            while container_stack:
                top_scope = container_stack[-1]
                scope_mode = str(top_scope.get("mode") or "")
                if scope_mode == "indent":
                    if stripped_line and indent <= int(top_scope.get("indent") or 0):
                        container_stack.pop()
                        continue
                    break
                if scope_mode == "brace":
                    if brace_depth < int(top_scope.get("brace_depth") or 0):
                        container_stack.pop()
                        continue
                    break
                container_stack.pop()

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
                    "section_path": current_section_path or current_symbol or self._derive_section_title(block_text),
                    "symbol_name": current_symbol,
                    "symbol_type": current_symbol_type,
                }
            )

        for line in lines:
            stripped_line = line.lstrip()
            indent = len(line) - len(stripped_line)
            pop_inactive_containers(indent, stripped_line)
            symbol_match = self._CODE_SYMBOL_RE.match(line)
            if symbol_match:
                flush()
                current_lines = [line]
                current_start = position
                current_symbol, current_symbol_type = self._extract_code_symbol(symbol_match.groupdict())
                container_path = current_container_path()
                current_section_path = (
                    f"{container_path} / {current_symbol}" if container_path and current_symbol else current_symbol or self._derive_section_title(line)
                )
                if current_symbol_type == "class" and current_symbol:
                    open_brace_count = line.count("{")
                    close_brace_count = line.count("}")
                    if open_brace_count > close_brace_count or "{" in line:
                        container_stack.append(
                            {
                                "name": current_symbol,
                                "mode": "brace",
                                "brace_depth": brace_depth + max(1, open_brace_count),
                            }
                        )
                    else:
                        container_stack.append(
                            {
                                "name": current_symbol,
                                "mode": "indent",
                                "indent": indent,
                            }
                        )
            else:
                if not current_lines:
                    current_start = position
                    current_section_path = current_container_path() or self._derive_section_title(line)
                current_lines.append(line)
            brace_depth += line.count("{") - line.count("}")
            position += len(line)

        flush()
        return self._materialize_blocks(blocks, base_metadata)

    def _chunk_structured_text(self, text: str, base_metadata: Dict[str, Any]) -> List[FileChunk]:
        normalized_text = str(text or "")
        if not normalized_text:
            return []

        # 优先尝试真正的 JSON/XML 树切分，只有解析失败时才回退到逐行启发式。
        json_blocks = self._try_build_json_blocks(normalized_text)
        if json_blocks:
            return self._materialize_blocks(json_blocks, base_metadata)

        xml_blocks = self._try_build_xml_blocks(normalized_text)
        if xml_blocks:
            return self._materialize_blocks(xml_blocks, base_metadata)

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
                    "structured_terms": current_path or self._derive_section_title(block_text),
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

    def _chunk_yaml_like(self, text: str, base_metadata: Dict[str, Any]) -> List[FileChunk]:
        """基于缩进恢复 YAML 层级路径，避免只保留当前行 key。"""
        normalized_text = str(text or "")
        if not normalized_text:
            return []

        lines = normalized_text.splitlines(keepends=True)
        blocks: List[Dict[str, Any]] = []
        path_stack: List[Dict[str, Any]] = []
        position = 0

        for line in lines:
            stripped_line = line.strip()
            if not stripped_line or stripped_line.startswith("#"):
                position += len(line)
                continue

            indent = len(line) - len(line.lstrip(" "))
            key_match = re.match(r'^(?P<key>[A-Za-z0-9_.\-"\']+)\s*:\s*(?P<value>.*)$', line.lstrip())
            list_item_match = re.match(r"^-\s+(?P<value>.+)$", line.lstrip())
            if not key_match and not list_item_match:
                position += len(line)
                continue

            while path_stack and indent <= int(path_stack[-1]["indent"]):
                path_stack.pop()

            if key_match:
                raw_key = key_match.group("key").strip().strip('"\'')
                raw_value = key_match.group("value").strip()
                current_path = ".".join([str(item["key"]) for item in path_stack] + [raw_key])
                if not raw_value:
                    # 目录型节点也保留为独立块，便于检索到上层配置节路径。
                    blocks.append(
                        {
                            "text": f"{current_path}:",
                            "start": position,
                            "section_title": raw_key,
                            "section_path": current_path,
                            "node_name": raw_key,
                            "leaf_value": None,
                        }
                    )
                    path_stack.append({"indent": indent, "key": raw_key})
                    position += len(line)
                    continue
                block_text = f"{current_path}: {raw_value}"
                blocks.append(
                    {
                        "text": block_text,
                        "start": position,
                        "section_title": raw_key,
                        "section_path": current_path,
                        "node_name": raw_key,
                        "leaf_value": raw_value[:120],
                    }
                )
                position += len(line)
                continue

            list_value = list_item_match.group("value").strip()
            parent_path = ".".join(str(item["key"]) for item in path_stack)
            list_index = sum(1 for block in blocks if str(block.get("section_path") or "").startswith(parent_path + "["))
            current_path = f"{parent_path}[{list_index}]" if parent_path else f"[{list_index}]"
            blocks.append(
                {
                    "text": f"{current_path}: {list_value}",
                    "start": position,
                    "section_title": current_path.split(".")[-1],
                    "section_path": current_path,
                    "node_name": current_path.split(".")[-1],
                    "leaf_value": list_value[:120],
                }
            )
            position += len(line)

        return self._materialize_blocks(blocks, base_metadata)

    def _chunk_key_value_config(self, text: str, base_metadata: Dict[str, Any], *, file_extension: str) -> List[FileChunk]:
        """恢复 TOML/INI/Properties 等配置文件的节路径与键路径。"""
        normalized_text = str(text or "")
        if not normalized_text:
            return []

        lines = normalized_text.splitlines(keepends=True)
        blocks: List[Dict[str, Any]] = []
        current_section: Optional[str] = None
        position = 0

        for line in lines:
            stripped_line = line.strip()
            if not stripped_line or stripped_line.startswith(("#", ";")):
                position += len(line)
                continue

            section_match = re.match(r"^\[(?P<section>[^\]]+)\]$", stripped_line)
            if section_match:
                current_section = section_match.group("section").strip()
                position += len(line)
                continue

            if file_extension == ".toml":
                key_value_match = re.match(r'^(?P<key>[A-Za-z0-9_.\-""\']+)\s*=\s*(?P<value>.+)$', stripped_line)
            else:
                key_value_match = re.match(r'^(?P<key>[A-Za-z0-9_.\-""\']+)\s*(?:=|:)\s*(?P<value>.+)$', stripped_line)
            if not key_value_match:
                position += len(line)
                continue

            raw_key = key_value_match.group("key").strip().strip('"\'')
            raw_value = key_value_match.group("value").strip()
            current_path = f"{current_section}.{raw_key}" if current_section else raw_key
            blocks.append(
                {
                    "text": f"{current_path}: {raw_value}",
                    "start": position,
                    "section_title": raw_key,
                    "section_path": current_path,
                    "node_name": raw_key,
                    "leaf_value": raw_value[:120],
                }
            )
            position += len(line)

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
            row_group_start = 1
            for row_offset, row in enumerate(rows or [], start=1):
                if not isinstance(row, list):
                    continue

                cleaned_row = [str(cell or "").strip() for cell in row]
                candidate_group = row_group + [cleaned_row]
                candidate_text = self._build_excel_chunk_text(sheet_name, columns, candidate_group, row_group_start)
                # Excel 分组优先按 token 预算控制，而不是固定 20 行；必要时再由下游二次细分。
                exceeds_budget = False
                if row_group:
                    exceeds_budget = self._count_tokens(candidate_text) > self._get_chunk_token_budget()

                if exceeds_budget:
                    content = self._build_excel_chunk_text(sheet_name, columns, row_group, row_group_start)
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
                    row_group = [cleaned_row]
                    row_group_start = row_offset
                    continue

                row_group.append(cleaned_row)

            if row_group:
                content = self._build_excel_chunk_text(sheet_name, columns, row_group, row_group_start)
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
            for key in (
                "symbol_name",
                "symbol_type",
                "node_name",
                "leaf_value",
                "column_headers",
                "source_tag",
                "block_type",
                "merged_section_paths",
                "structured_terms",
                "slide_title",
                "source_region",
                "notes_included",
            ):
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
            end = self._prefer_semantic_boundary(normalized_text, start, end)
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
            start = self._resolve_next_chunk_start(normalized_text, start, end)
        return chunks

    def _fit_chunk_end_by_token_budget(self, text: str, start: int, end: int) -> int:
        if self.max_chunk_tokens is None:
            return end

        if start >= end:
            return end

        candidate = text[start:end].strip()
        if not candidate:
            return end

        if self._count_tokens(candidate) <= self.max_chunk_tokens:
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
            if self._count_tokens(sample) <= self.max_chunk_tokens:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        return self._prefer_semantic_boundary(text, start, max(start + 1, best), hard_limit=max(start + 1, best))

    def _build_chunk_metadata(self, metadata: Dict[str, Any], start_char: int, end_char: int, content: str) -> Dict[str, Any]:
        chunk_metadata = dict(metadata or {})
        chunk_metadata["start_char"] = start_char
        chunk_metadata["end_char"] = end_char
        chunk_metadata["token_count"] = self._count_tokens(content)
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
        chunk_metadata.setdefault("slide_title", None)
        chunk_metadata.setdefault("source_region", None)
        chunk_metadata.setdefault("notes_included", None)
        chunk_metadata.setdefault("structured_terms", self._build_structured_terms_text(chunk_metadata))
        return chunk_metadata

    @staticmethod
    def _build_structured_terms_text(metadata: Dict[str, Any]) -> Optional[str]:
        """汇总结构化检索辅助字段，供稀疏召回和重排统一复用。"""
        values: List[str] = []
        for field in (
            "section_title",
            "section_path",
            "sheet_name",
            "symbol_name",
            "symbol_type",
            "node_name",
            "leaf_value",
            "slide_title",
            "source_region",
        ):
            value = metadata.get(field)
            if value:
                values.append(str(value))

        column_headers = metadata.get("column_headers")
        if isinstance(column_headers, list):
            values.extend(str(item) for item in column_headers if item)
        elif column_headers:
            values.append(str(column_headers))

        deduplicated: List[str] = []
        for value in values:
            normalized = str(value).strip()
            if normalized and normalized not in deduplicated:
                deduplicated.append(normalized)
        return " ".join(deduplicated) if deduplicated else None

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

    def _extract_pdf_blocks(self, text: str) -> List[str]:
        """为 PDF 文本提取更接近语义边界的逻辑块。"""
        paragraphs = self._split_text_into_blocks(text, strategy="paragraph")
        if not paragraphs:
            return []

        blocks: List[str] = []
        current_lines: List[str] = []
        for paragraph in paragraphs:
            normalized_paragraph = paragraph.strip()
            if not normalized_paragraph:
                continue
            starts_new_block = self._looks_like_heading(normalized_paragraph) or self._looks_like_list_item(normalized_paragraph)
            if starts_new_block and current_lines:
                blocks.append("\n\n".join(current_lines).strip())
                current_lines = [normalized_paragraph]
                continue
            current_lines.append(normalized_paragraph)

        if current_lines:
            blocks.append("\n\n".join(current_lines).strip())
        return [block for block in blocks if block]

    def _try_build_json_blocks(self, text: str) -> List[Dict[str, Any]]:
        try:
            parsed = json.loads(text)
        except Exception:
            return []

        blocks: List[Dict[str, Any]] = []
        position = 0

        def visit(node: Any, path: str) -> None:
            nonlocal position
            if isinstance(node, dict):
                for key, value in node.items():
                    child_path = f"{path}.{key}" if path else str(key)
                    visit(value, child_path)
                return

            if isinstance(node, list):
                if node and all(not isinstance(item, (dict, list)) for item in node):
                    block_text = f"{path}: {json.dumps(node, ensure_ascii=False)}"
                    blocks.append(
                        {
                            "text": block_text,
                            "start": position,
                            "section_title": path.split(".")[-1] if path else "root",
                            "section_path": path or "root",
                            "node_name": path.split(".")[-1] if path else "root",
                            "leaf_value": json.dumps(node, ensure_ascii=False)[:120],
                        }
                    )
                    position += len(block_text) + 2
                    return

                for index, item in enumerate(node):
                    child_path = f"{path}[{index}]" if path else f"[{index}]"
                    visit(item, child_path)
                return

            leaf_text = json.dumps(node, ensure_ascii=False)
            block_text = f"{path}: {leaf_text}" if path else leaf_text
            blocks.append(
                {
                    "text": block_text,
                    "start": position,
                    "section_title": path.split(".")[-1] if path else "root",
                    "section_path": path or "root",
                    "node_name": path.split(".")[-1] if path else "root",
                    "leaf_value": leaf_text[:120],
                }
            )
            position += len(block_text) + 2

        visit(parsed, "")
        return blocks

    def _try_build_xml_blocks(self, text: str) -> List[Dict[str, Any]]:
        try:
            root = ET.fromstring(text)
        except Exception:
            return []

        blocks: List[Dict[str, Any]] = []
        position = 0

        def visit(node: ET.Element, path: str) -> None:
            nonlocal position
            child_path = f"{path}/{node.tag}" if path else node.tag
            attributes_text = " ".join(f"{key}={value}" for key, value in node.attrib.items())
            text_value = (node.text or "").strip()
            child_tags = [child.tag for child in list(node)]
            if text_value or attributes_text or not child_tags:
                block_lines = [f"path: {child_path}"]
                if attributes_text:
                    block_lines.append(f"attributes: {attributes_text}")
                if child_tags:
                    block_lines.append(f"children: {', '.join(child_tags)}")
                if text_value:
                    block_lines.append(f"text: {text_value}")
                block_text = "\n".join(block_lines)
                blocks.append(
                    {
                        "text": block_text,
                        "start": position,
                        "section_title": node.tag,
                        "section_path": child_path,
                        "node_name": node.tag,
                        "leaf_value": text_value[:120] if text_value else None,
                    }
                )
                position += len(block_text) + 2

            for child in list(node):
                visit(child, child_path)

        visit(root, "")
        return blocks

    def _prefer_semantic_boundary(self, text: str, start: int, end: int, hard_limit: Optional[int] = None) -> int:
        """优先把切块结束位置吸附到段落、句子或空白边界。"""
        if end >= len(text):
            return len(text)

        upper_bound = min(len(text), hard_limit if hard_limit is not None else end)
        lower_bound = max(start + 1, upper_bound - min(120, max(20, self.chunk_size // 4)))
        for index in range(upper_bound, lower_bound - 1, -1):
            if self._is_semantic_boundary(text, index):
                return index
        return upper_bound

    def _resolve_next_chunk_start(self, text: str, previous_start: int, previous_end: int) -> int:
        if self.chunk_overlap <= 0:
            return previous_end

        target_start = max(previous_end - self.chunk_overlap, previous_start + 1)
        search_end = min(len(text), target_start + 80)
        for index in range(target_start, search_end + 1):
            if self._is_semantic_boundary(text, index):
                return index

        search_start = max(previous_start + 1, target_start - 80)
        for index in range(target_start, search_start - 1, -1):
            if self._is_semantic_boundary(text, index):
                return index
        return target_start

    def _is_semantic_boundary(self, text: str, index: int) -> bool:
        if index <= 0 or index >= len(text):
            return True
        previous_char = text[index - 1]
        next_char = text[index]
        if previous_char == "\n" and next_char == "\n":
            return True
        if previous_char == "\n":
            return True
        if previous_char in "。！？!?；;:." and (next_char.isspace() or self._is_cjk_char(next_char)):
            return True
        if previous_char.isspace():
            return True
        return False

    def _looks_like_list_item(self, text: str) -> bool:
        first_line = str(text or "").splitlines()[0].strip() if str(text or "").splitlines() else ""
        return bool(re.match(r"^(?:[-*•]|\d+[.)]|[A-Za-z][.)]|[一二三四五六七八九十]+[、.])\s+", first_line))

    def _build_default_token_counter(self) -> Optional[Callable[[str], int]]:
        """尽量使用真实 tokenizer 计数，避免继续走粗略字符估算。"""
        try:
            import tiktoken

            encoder = tiktoken.get_encoding(self._DEFAULT_TOKENIZER_NAME)
            return lambda text: len(encoder.encode(str(text or ""), disallowed_special=()))
        except Exception:
            return None

    def _get_chunk_token_budget(self) -> int:
        if self.max_chunk_tokens is not None:
            return max(1, int(self.max_chunk_tokens))
        return max(1, self._estimate_token_count("x" * self.chunk_size))

    def _count_tokens(self, text: str) -> int:
        if callable(self.token_counter):
            try:
                return max(0, int(self.token_counter(text)))
            except Exception:
                pass
        return self._estimate_token_count(text)

    @staticmethod
    def _is_cjk_char(character: str) -> bool:
        return bool(character and "\u4e00" <= character <= "\u9fff")

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
