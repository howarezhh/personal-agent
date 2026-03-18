from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import List

from backend.file_processors.parsers.base_parser import BaseParser, ParsedContent


class _MainContentHTMLParser(HTMLParser):
    BLOCK_TAGS = {"p", "div", "section", "article", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "br"}
    SKIP_TAGS = {"script", "style", "noscript"}
    PRIORITY_TAG_ATTRS = {"main", "article"}

    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.skip_depth = 0
        self.capture_priority_depth = 0
        self.current_priority_text: List[str] = []
        self.fallback_text: List[str] = []
        self.title_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs):
        tag = (tag or "").lower()
        attrs_dict = {str(key).lower(): str(value or "") for key, value in attrs}
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        if tag == "title":
            self.in_title = True
        if tag in self.PRIORITY_TAG_ATTRS or attrs_dict.get("role", "").lower() == "main":
            self.capture_priority_depth += 1
        class_name = attrs_dict.get("class", "").lower()
        element_id = attrs_dict.get("id", "").lower()
        if any(token in class_name or token in element_id for token in ("content", "article", "main", "post", "body")):
            self.capture_priority_depth += 1
        if tag in self.BLOCK_TAGS:
            self._append_break()

    def handle_endtag(self, tag: str):
        tag = (tag or "").lower()
        if tag in self.SKIP_TAGS and self.skip_depth > 0:
            self.skip_depth -= 1
            return
        if tag == "title":
            self.in_title = False
        if tag in self.PRIORITY_TAG_ATTRS and self.capture_priority_depth > 0:
            self.capture_priority_depth -= 1
        if tag in self.BLOCK_TAGS:
            self._append_break()

    def handle_data(self, data: str):
        if self.skip_depth > 0:
            return
        text = " ".join(str(data or "").split())
        if not text:
            return
        if self.in_title:
            self.title_parts.append(text)
        target = self.current_priority_text if self.capture_priority_depth > 0 else self.fallback_text
        target.append(text)

    def _append_break(self):
        target = self.current_priority_text if self.capture_priority_depth > 0 else self.fallback_text
        if target and target[-1] != "\n":
            target.append("\n")

    def get_text(self) -> str:
        priority = self._normalize_text(self.current_priority_text)
        fallback = self._normalize_text(self.fallback_text)
        return priority or fallback

    def get_title(self) -> str:
        return " ".join(self.title_parts).strip()

    @staticmethod
    def _normalize_text(parts: List[str]) -> str:
        text = " ".join(parts)
        lines = [line.strip() for line in text.split("\n")]
        compact_lines = [line for line in lines if line]
        return "\n\n".join(compact_lines).strip()


class HtmlParser(BaseParser):
    async def parse(self, file_path: str) -> ParsedContent:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"HTML file does not exist: {path}")

        raw_html = path.read_text(encoding="utf-8", errors="ignore")
        parser = _MainContentHTMLParser()
        parser.feed(raw_html)
        text = parser.get_text()
        title = parser.get_title()

        metadata = {
            "parser": "html_main_content",
            "title": title,
            "char_count": len(text),
            "has_text": bool(text),
            "empty_content": not bool(text),
        }
        return self.finalize_parsed_content(file_path, ParsedContent(text=text, metadata=metadata))

    def supports(self, file_extension: str) -> bool:
        return file_extension.lower() in [".html", ".htm"]

    def get_supported_extensions(self) -> List[str]:
        return [".html", ".htm"]
