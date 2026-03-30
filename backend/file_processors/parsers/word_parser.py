from __future__ import annotations

import re
from typing import Iterable, List

from backend.file_processors.parsers.base_parser import BaseParser, ParsedContent


class WordParser(BaseParser):
    _WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

    def __init__(self):
        super().__init__()

    async def parse(self, file_path: str) -> ParsedContent:
        try:
            from docx import Document
            from docx.document import Document as DocumentObject
            from docx.oxml.table import CT_Tbl
            from docx.oxml.text.paragraph import CT_P
            from docx.table import Table
            from docx.text.paragraph import Paragraph
        except ImportError:
            raise ImportError("python-docx is not installed. Please install it: pip install python-docx")

        def iter_body_blocks(document: DocumentObject) -> Iterable[Paragraph | Table]:
            """按 Word 正文真实顺序遍历段落和表格，避免段落/表格顺序丢失。"""
            for child in document.element.body.iterchildren():
                if isinstance(child, CT_P):
                    yield Paragraph(child, document)
                elif isinstance(child, CT_Tbl):
                    yield Table(child, document)

        try:
            doc = Document(file_path)
            blocks = []
            tables_data = []
            heading_stack: List[str] = []
            paragraph_count = 0
            table_count = 0

            for body_block in iter_body_blocks(doc):
                if isinstance(body_block, Paragraph):
                    paragraph_text = str(body_block.text or "").strip()
                    if not paragraph_text:
                        continue

                    paragraph_count += 1
                    heading_level = self._extract_heading_level(body_block)
                    if heading_level is not None:
                        heading_stack = heading_stack[: heading_level - 1]
                        heading_stack.append(paragraph_text)
                        section_path = " / ".join(heading_stack)
                        blocks.append(
                            {
                                "block_type": "heading",
                                "text": f"{'#' * heading_level} {paragraph_text}",
                                "heading_level": heading_level,
                                "style_name": self._read_style_name(body_block),
                                "section_title": paragraph_text,
                                "section_path": section_path,
                            }
                        )
                        continue

                    current_section_path = " / ".join(heading_stack) if heading_stack else None
                    current_section_title = heading_stack[-1] if heading_stack else self._derive_section_title(paragraph_text)
                    blocks.append(
                        {
                            "block_type": "paragraph",
                            "text": paragraph_text,
                            "heading_level": None,
                            "style_name": self._read_style_name(body_block),
                            "section_title": current_section_title,
                            "section_path": current_section_path or current_section_title,
                        }
                    )
                    continue

                if not isinstance(body_block, Table):
                    continue

                table_count += 1
                row_values = []
                for row in body_block.rows:
                    cleaned_row = [str(cell.text or "").strip() for cell in row.cells]
                    if any(cleaned_row):
                        row_values.append(cleaned_row)

                if not row_values:
                    continue

                columns = [value or f"column_{index + 1}" for index, value in enumerate(row_values[0])]
                data_rows = row_values[1:] if len(row_values) > 1 else []
                current_section_path = " / ".join(heading_stack) if heading_stack else None
                table_section_title = f"表格 {table_count}"
                table_section_path = f"{current_section_path} / {table_section_title}" if current_section_path else table_section_title

                table_lines = [f"[{table_section_title}]"]
                table_lines.append("列: " + " | ".join(column for column in columns if column))
                for row_index, row in enumerate(data_rows, start=1):
                    cells = [
                        f"{column}: {value}"
                        for column, value in zip(columns, row)
                        if value
                    ]
                    if cells:
                        table_lines.append(f"第{row_index}行 | " + " | ".join(cells))

                blocks.append(
                    {
                        "block_type": "table",
                        "text": "\n".join(table_lines),
                        "heading_level": None,
                        "table_index": table_count,
                        "section_title": table_section_title,
                        "section_path": table_section_path,
                        "column_headers": columns,
                    }
                )
                tables_data.append(
                    {
                        "table_index": table_count,
                        "columns": columns,
                        "rows": data_rows,
                    }
                )

            extra_blocks = self._extract_additional_blocks(doc, start_offset=len("\n\n".join(block["text"] for block in blocks if block.get("text"))))
            if extra_blocks:
                blocks.extend(extra_blocks)

            full_text = "\n\n".join(block["text"] for block in blocks if block.get("text"))
            metadata = {
                "paragraph_count": paragraph_count,
                "table_count": len(tables_data),
                "block_count": len(blocks),
                "header_footer_block_count": sum(1 for block in blocks if block.get("source_region") in {"header", "footer"}),
                "textbox_block_count": sum(1 for block in blocks if block.get("source_region") == "textbox"),
                "parser": "python-docx-structured",
            }

            try:
                core_properties = doc.core_properties
                if core_properties.title:
                    metadata["title"] = core_properties.title
                if core_properties.author:
                    metadata["author"] = core_properties.author
                if core_properties.subject:
                    metadata["subject"] = core_properties.subject
                if core_properties.created:
                    metadata["created"] = core_properties.created.isoformat()
                if core_properties.modified:
                    metadata["modified"] = core_properties.modified.isoformat()
            except Exception as error:
                self.logger.warning(f"Failed to extract document properties: {str(error)}")

            return ParsedContent(
                text=full_text,
                metadata=metadata,
                tables=tables_data if tables_data else None,
                blocks=blocks if blocks else None,
            )

        except Exception as error:
            self.logger.error(f"Failed to parse Word document: {str(error)}")
            raise

    @staticmethod
    def _read_style_name(paragraph) -> str:
        return str(getattr(getattr(paragraph, "style", None), "name", "") or "")

    def _extract_heading_level(self, paragraph) -> int | None:
        # 先看当前样式名；若是自定义样式，再沿 base_style 链和 outline level 继续判断。
        style = getattr(paragraph, "style", None)
        style_name = self._read_style_name(paragraph).strip().lower()
        style_level = self._extract_heading_level_from_style_name(style_name)
        if style_level is not None:
            return style_level

        outline_level = self._read_outline_level(paragraph)
        if outline_level is not None:
            return outline_level

        visited_style_ids: set[int] = set()
        current_style = style
        while current_style is not None and id(current_style) not in visited_style_ids:
            visited_style_ids.add(id(current_style))
            current_style_name = str(getattr(current_style, "name", "") or "").strip().lower()
            current_style_level = self._extract_heading_level_from_style_name(current_style_name)
            if current_style_level is not None:
                return current_style_level

            outline_level = self._read_style_outline_level(current_style)
            if outline_level is not None:
                return outline_level

            current_style = getattr(current_style, "base_style", None)

        return None

    @staticmethod
    def _extract_heading_level_from_style_name(style_name: str) -> int | None:
        normalized_name = str(style_name or "").strip().lower()
        if not normalized_name:
            return None
        if "heading" not in normalized_name and "标题" not in normalized_name:
            return None

        match = re.search(r"(\d+)", normalized_name)
        if not match:
            return 1
        return max(1, min(int(match.group(1)), 6))

    def _read_outline_level(self, paragraph) -> int | None:
        try:
            paragraph_properties = getattr(getattr(paragraph, "_p", None), "pPr", None)
            outline_element = getattr(paragraph_properties, "outlineLvl", None)
            if outline_element is not None:
                outline_value = int(getattr(outline_element, "val", getattr(outline_element, "w_val", 0)))
                return max(1, min(outline_value + 1, 6))
        except Exception:
            pass
        return self._read_style_outline_level(getattr(paragraph, "style", None))

    @staticmethod
    def _read_style_outline_level(style) -> int | None:
        if style is None:
            return None
        try:
            xpath_result = style.element.xpath(".//w:pPr/w:outlineLvl/@w:val")
        except Exception:
            xpath_result = []
        if not xpath_result:
            return None
        try:
            return max(1, min(int(xpath_result[0]) + 1, 6))
        except Exception:
            return None

    @staticmethod
    def _derive_section_title(text: str) -> str:
        return str(text or "").splitlines()[0].strip()[:120]

    def _extract_additional_blocks(self, doc, *, start_offset: int) -> list[dict]:
        """补充提取页眉、页脚和文本框中的可读文本。"""
        blocks: list[dict] = []
        current_offset = start_offset
        seen_texts: set[tuple[str, str]] = set()

        def append_block(*, region: str, title: str, text: str) -> None:
            nonlocal current_offset
            normalized_text = str(text or "").strip()
            if not normalized_text:
                return
            dedupe_key = (region, normalized_text)
            if dedupe_key in seen_texts:
                return
            seen_texts.add(dedupe_key)
            section_path = f"附加内容 / {title}"
            blocks.append(
                {
                    "block_type": "paragraph",
                    "text": normalized_text,
                    "start": current_offset,
                    "section_title": title,
                    "section_path": section_path,
                    "source_region": region,
                }
            )
            current_offset += len(normalized_text) + 2

        for section_index, section in enumerate(getattr(doc, "sections", []) or [], start=1):
            for paragraph in getattr(getattr(section, "header", None), "paragraphs", []) or []:
                append_block(region="header", title=f"页眉 {section_index}", text=paragraph.text)
            for paragraph in getattr(getattr(section, "footer", None), "paragraphs", []) or []:
                append_block(region="footer", title=f"页脚 {section_index}", text=paragraph.text)

        try:
            textboxes = doc.element.xpath(".//w:txbxContent", namespaces=self._WORD_NS)
        except Exception:
            textboxes = []
        for textbox_index, textbox in enumerate(textboxes, start=1):
            try:
                parts = [node.text.strip() for node in textbox.xpath(".//w:t", namespaces=self._WORD_NS) if node.text and node.text.strip()]
            except Exception:
                parts = []
            append_block(region="textbox", title=f"文本框 {textbox_index}", text="\n".join(parts))

        return blocks

    def supports(self, file_extension: str) -> bool:
        return file_extension.lower() in [".docx"]

    def get_supported_extensions(self) -> List[str]:
        return [".docx"]
