from __future__ import annotations

from pathlib import Path
from typing import List
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from backend.file_processors.parsers.base_parser import BaseParser, ParsedContent

PRESENTATION_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
}


class PptxParser(BaseParser):
    async def parse(self, file_path: str) -> ParsedContent:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"PPTX file does not exist: {path}")

        pages = []
        title = ""
        author = ""
        with ZipFile(path, "r") as archive:
            slide_names = sorted(
                [name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")],
                key=self._slide_sort_key,
            )
            for index, slide_name in enumerate(slide_names, start=1):
                slide_xml = archive.read(slide_name)
                slide_text = self._extract_slide_text(slide_xml)
                if slide_text:
                    pages.append({"page_number": index, "text": slide_text, "char_count": len(slide_text)})

            if "docProps/core.xml" in archive.namelist():
                title, author = self._extract_core_properties(archive.read("docProps/core.xml"))

        full_text = "\n\n".join(page["text"] for page in pages)
        metadata = {
            "parser": "pptx_zip_xml",
            "title": title,
            "author": author,
            "total_slides": len(pages),
            "has_text": bool(full_text),
            "empty_content": not bool(full_text),
        }
        return self.finalize_parsed_content(file_path, ParsedContent(text=full_text, metadata=metadata, pages=pages))

    @staticmethod
    def _slide_sort_key(name: str) -> int:
        digits = "".join(ch for ch in Path(name).stem if ch.isdigit())
        return int(digits or 0)

    @staticmethod
    def _extract_slide_text(xml_bytes: bytes) -> str:
        root = ET.fromstring(xml_bytes)
        texts = [node.text.strip() for node in root.findall(".//a:t", PRESENTATION_NS) if node.text and node.text.strip()]
        return "\n".join(texts).strip()

    @staticmethod
    def _extract_core_properties(xml_bytes: bytes) -> tuple[str, str]:
        root = ET.fromstring(xml_bytes)
        title = root.findtext("dc:title", default="", namespaces=PRESENTATION_NS) or ""
        author = root.findtext("dc:creator", default="", namespaces=PRESENTATION_NS) or ""
        return title.strip(), author.strip()

    def supports(self, file_extension: str) -> bool:
        return file_extension.lower() == ".pptx"

    def get_supported_extensions(self) -> List[str]:
        return [".pptx"]
