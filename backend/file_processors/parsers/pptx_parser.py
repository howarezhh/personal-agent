from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import List
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from backend.file_processors.parsers.base_parser import BaseParser, ParsedContent

PRESENTATION_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
NOTES_SLIDE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"


class PptxParser(BaseParser):
    async def parse(self, file_path: str) -> ParsedContent:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"PPTX file does not exist: {path}")

        pages = []
        title = ""
        author = ""
        notes_count = 0
        with ZipFile(path, "r") as archive:
            slide_names = sorted(
                [name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")],
                key=self._slide_sort_key,
            )
            for index, slide_name in enumerate(slide_names, start=1):
                slide_xml = archive.read(slide_name)
                slide_text = self._extract_slide_text(slide_xml)
                # 讲稿页通过关系文件绑定，不能假设 slideN 必然对应 notesSlideN。
                notes_name = self._resolve_notes_slide_name(archive, slide_name)
                notes_text = self._extract_slide_text(archive.read(notes_name)) if notes_name in archive.namelist() else ""
                if notes_text:
                    notes_count += 1
                combined_text = slide_text
                if notes_text:
                    combined_text = f"{slide_text}\n\n[讲稿]\n{notes_text}".strip()
                if combined_text:
                    pages.append(
                        {
                            "page_number": index,
                            "text": combined_text,
                            "char_count": len(combined_text),
                            "slide_title": slide_text.splitlines()[0].strip() if slide_text.splitlines() else None,
                            "notes_included": bool(notes_text),
                        }
                    )

            if "docProps/core.xml" in archive.namelist():
                title, author = self._extract_core_properties(archive.read("docProps/core.xml"))

        pages = self._apply_slide_start_offsets(pages)
        full_text = "\n\n".join(page["text"] for page in pages if page.get("text"))
        metadata = {
            "parser": "pptx_zip_xml",
            "title": title,
            "author": author,
            "total_slides": len(pages),
            "notes_slide_count": notes_count,
            "has_text": bool(full_text),
            "empty_content": not bool(full_text),
        }
        return ParsedContent(text=full_text, metadata=metadata, pages=pages)

    @staticmethod
    def _slide_sort_key(name: str) -> int:
        digits = "".join(ch for ch in Path(name).stem if ch.isdigit())
        return int(digits or 0)

    @staticmethod
    def _extract_slide_text(xml_bytes: bytes) -> str:
        root = ET.fromstring(xml_bytes)
        lines: List[str] = []
        # 按段落提取文本，尽量保留列表层级，而不是把所有文本节点彻底拍平成一列。
        for paragraph in root.findall(".//a:p", PRESENTATION_NS):
            text_fragments = [node.text for node in paragraph.findall(".//a:t", PRESENTATION_NS) if node.text and node.text.strip()]
            paragraph_text = "".join(text_fragments).strip()
            if not paragraph_text:
                continue

            paragraph_properties = paragraph.find("a:pPr", PRESENTATION_NS)
            indent_level = 0
            has_bullet = False
            if paragraph_properties is not None:
                indent_level = int(paragraph_properties.attrib.get("lvl", 0) or 0)
                has_bullet = any(child.tag.endswith(("buChar", "buAutoNum", "buBlip")) for child in list(paragraph_properties))

            prefix = f"{'  ' * indent_level}- " if has_bullet or indent_level > 0 else ""
            lines.append(f"{prefix}{paragraph_text}".rstrip())

        return "\n".join(lines).strip()

    @staticmethod
    def _extract_core_properties(xml_bytes: bytes) -> tuple[str, str]:
        root = ET.fromstring(xml_bytes)
        title = root.findtext("dc:title", default="", namespaces=PRESENTATION_NS) or ""
        author = root.findtext("dc:creator", default="", namespaces=PRESENTATION_NS) or ""
        return title.strip(), author.strip()

    @staticmethod
    def _apply_slide_start_offsets(pages: List[dict]) -> List[dict]:
        """为每页幻灯片补齐全局字符偏移，保证切块定位稳定。"""
        current_offset = 0
        normalized_pages: List[dict] = []
        for page in pages or []:
            normalized_page = dict(page)
            normalized_page["start_char"] = current_offset
            slide_text = str(normalized_page.get("text") or "")
            current_offset += len(slide_text) + 2
            normalized_pages.append(normalized_page)
        return normalized_pages

    def _resolve_notes_slide_name(self, archive: ZipFile, slide_name: str) -> str:
        relationship_path = f"ppt/slides/_rels/{Path(slide_name).name}.rels"
        if relationship_path in archive.namelist():
            root = ET.fromstring(archive.read(relationship_path))
            for relation in root.findall("rel:Relationship", PRESENTATION_NS):
                if relation.attrib.get("Type") != NOTES_SLIDE_REL_TYPE:
                    continue
                target = str(relation.attrib.get("Target") or "").strip()
                if not target:
                    break
                slide_dir = PurePosixPath(slide_name).parent
                resolved_parts: list[str] = []
                for part in (slide_dir / target).parts:
                    if part in {"", "."}:
                        continue
                    if part == "..":
                        if resolved_parts:
                            resolved_parts.pop()
                        continue
                    resolved_parts.append(part)
                return "/".join(resolved_parts)

        slide_number = self._slide_sort_key(slide_name)
        return f"ppt/notesSlides/notesSlide{slide_number}.xml"

    def supports(self, file_extension: str) -> bool:
        return file_extension.lower() == ".pptx"

    def get_supported_extensions(self) -> List[str]:
        return [".pptx"]
