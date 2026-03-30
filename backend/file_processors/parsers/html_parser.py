from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
import re
from typing import List, Optional

from backend.file_processors.parsers.base_parser import BaseParser, ParsedContent
from backend.file_processors.parsers.text_readers import read_html_text_with_fallback


@dataclass
class _HtmlNode:
    tag: str
    attrs: dict[str, str]
    parent: Optional["_HtmlNode"] = None
    children: List["_HtmlNode"] = field(default_factory=list)
    text_parts: List[str] = field(default_factory=list)


class _HTMLTreeBuilder(HTMLParser):
    """构建轻量 DOM 树。

    不引入第三方依赖，直接把 HTML 解析成树结构，后续再做正文抽取与结构化渲染。
    """

    SKIP_TAGS = {"script", "style", "noscript", "template"}
    VOID_TAGS = {"br", "img", "meta", "link", "hr", "input", "source"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HtmlNode(tag="document", attrs={})
        self.stack: List[_HtmlNode] = [self.root]
        self.skip_stack: List[str] = []
        self.title_parts: List[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        normalized_tag = str(tag or "").lower()
        attrs_dict = {str(key).lower(): str(value or "") for key, value in attrs}
        node = _HtmlNode(tag=normalized_tag, attrs=attrs_dict, parent=self.stack[-1])
        self.stack[-1].children.append(node)

        if normalized_tag == "title":
            self.in_title = True

        if normalized_tag in self.VOID_TAGS:
            return

        self.stack.append(node)
        if normalized_tag in self.SKIP_TAGS:
            self.skip_stack.append(normalized_tag)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = str(tag or "").lower()
        if normalized_tag == "title":
            self.in_title = False

        while len(self.stack) > 1:
            node = self.stack.pop()
            if node.tag == normalized_tag:
                break

        if self.skip_stack and self.skip_stack[-1] == normalized_tag:
            self.skip_stack.pop()

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self.skip_stack:
            return

        text = str(data or "")
        if not text.strip():
            return

        if self.in_title:
            self.title_parts.append(text)

        self.stack[-1].text_parts.append(text)

    def get_title(self) -> str:
        return _normalize_inline_text(" ".join(self.title_parts))


class _MainContentExtractor:
    POSITIVE_ATTR_TOKENS = {"content", "article", "main", "post", "entry", "body", "markdown", "readme"}
    NEGATIVE_ATTR_TOKENS = {"nav", "menu", "sidebar", "footer", "comment", "breadcrumb", "advert", "ads"}
    NOISE_TAGS = {"script", "style", "noscript", "template", "nav", "footer", "aside"}
    CANDIDATE_TAGS = {"body", "main", "article", "section", "div"}
    HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

    def extract(self, root: _HtmlNode) -> tuple[str, str, List[dict[str, object]]]:
        body = self._find_first(root, "body") or root
        content_root = self._pick_main_content_root(body)
        rendered_lines: List[str] = []
        self._render_node(content_root, rendered_lines, section_depth=0, list_depth=0)
        return _normalize_block_text(rendered_lines), content_root.tag, self._build_blocks(content_root)

    def _build_blocks(self, content_root: _HtmlNode) -> List[dict[str, object]]:
        """保留 HTML 正文的结构化块，供后续分块阶段复用。"""
        blocks: List[dict[str, object]] = []
        current_start = 0

        def append_block(*, text: str, block_type: str, source_tag: str, section_path: Optional[str], heading_level: Optional[int]) -> None:
            nonlocal current_start
            normalized_text = _normalize_block_text(str(text or "").splitlines()) if block_type == "table" else str(text or "").strip()
            if not normalized_text:
                return
            section_title = (section_path.split(" / ")[-1] if section_path else None) or normalized_text.splitlines()[0][:120]
            blocks.append(
                {
                    "text": normalized_text,
                    "start": current_start,
                    "block_type": block_type,
                    "source_tag": source_tag,
                    "section_title": section_title,
                    "section_path": section_path or section_title,
                    "heading_level": heading_level,
                }
            )
            current_start += len(normalized_text) + 2

        def visit(node: _HtmlNode, heading_stack: List[dict[str, object]], section_depth: int) -> List[dict[str, object]]:
            if self._is_noise_node(node):
                return heading_stack

            if node.tag in {"article", "section"}:
                structure_label = self._extract_structure_label(node)
                next_stack = list(heading_stack)
                if structure_label:
                    heading_level = min(6, section_depth + 2)
                    next_stack = [item for item in next_stack if int(item["level"]) < heading_level]
                    next_stack.append({"level": heading_level, "title": structure_label})
                    append_block(
                        text=f"{'#' * heading_level} {structure_label}",
                        block_type="heading",
                        source_tag=node.tag,
                        section_path=" / ".join(str(item["title"]) for item in next_stack),
                        heading_level=heading_level,
                    )
                for child in node.children:
                    next_stack = visit(child, next_stack, section_depth + 1)
                return next_stack

            if node.tag in self.HEADING_LEVELS:
                heading_text = self._collect_inline_text(node)
                if not heading_text:
                    return heading_stack
                heading_level = self.HEADING_LEVELS[node.tag]
                next_stack = [item for item in heading_stack if int(item["level"]) < heading_level]
                next_stack.append({"level": heading_level, "title": heading_text})
                append_block(
                    text=f"{'#' * heading_level} {heading_text}",
                    block_type="heading",
                    source_tag=node.tag,
                    section_path=" / ".join(str(item["title"]) for item in next_stack),
                    heading_level=heading_level,
                )
                return next_stack

            current_section_path = " / ".join(str(item["title"]) for item in heading_stack) if heading_stack else None

            if node.tag in {"p", "blockquote", "pre"}:
                paragraph = self._collect_inline_text(node, preserve_line_breaks=node.tag == "pre")
                append_block(
                    text=paragraph,
                    block_type="paragraph",
                    source_tag=node.tag,
                    section_path=current_section_path,
                    heading_level=int(heading_stack[-1]["level"]) if heading_stack else None,
                )
                return heading_stack

            if node.tag in {"ul", "ol"}:
                ordered = node.tag == "ol"
                item_index = 1
                for child in node.children:
                    if child.tag != "li":
                        continue
                    inline_parts: List[str] = []
                    for grandchild in child.children:
                        if grandchild.tag in {"ul", "ol"}:
                            continue
                        rendered = self._collect_inline_text(grandchild)
                        if rendered:
                            inline_parts.append(rendered)
                    if child.text_parts:
                        inline_parts.insert(0, _normalize_inline_text(" ".join(child.text_parts)))
                    inline_text = _normalize_inline_text(" ".join(part for part in inline_parts if part))
                    prefix = f"{item_index}. " if ordered else "- "
                    append_block(
                        text=f"{prefix}{inline_text}",
                        block_type="list_item",
                        source_tag=child.tag,
                        section_path=current_section_path,
                        heading_level=int(heading_stack[-1]["level"]) if heading_stack else None,
                    )
                    for grandchild in child.children:
                        if grandchild.tag in {"ul", "ol"}:
                            visit(grandchild, heading_stack, section_depth)
                    item_index += 1
                return heading_stack

            if node.tag == "table":
                table_lines: List[str] = []
                for row in [child for child in node.children if child.tag == "tr"]:
                    cells = [self._collect_inline_text(cell) for cell in row.children if cell.tag in {"td", "th"}]
                    if any(cells):
                        table_lines.append(" | ".join(cell for cell in cells if cell))
                append_block(
                    text="\n".join(table_lines),
                    block_type="table",
                    source_tag=node.tag,
                    section_path=current_section_path,
                    heading_level=int(heading_stack[-1]["level"]) if heading_stack else None,
                )
                return heading_stack

            direct_text = _normalize_inline_text(" ".join(node.text_parts))
            if direct_text and not any(child.tag in {"p", "ul", "ol", "table", *self.HEADING_LEVELS.keys()} for child in node.children):
                append_block(
                    text=direct_text,
                    block_type="paragraph",
                    source_tag=node.tag,
                    section_path=current_section_path,
                    heading_level=int(heading_stack[-1]["level"]) if heading_stack else None,
                )

            next_stack = heading_stack
            for child in node.children:
                next_stack = visit(child, next_stack, section_depth)
            return next_stack

        visit(content_root, [], 0)
        return blocks

    def _pick_main_content_root(self, body: _HtmlNode) -> _HtmlNode:
        candidates = [node for node in self._walk(body) if node.tag in self.CANDIDATE_TAGS and not self._is_noise_node(node)]
        if not candidates:
            return body

        scored_candidates = [
            (self._score_candidate(node), self._visible_text_length(node), node)
            for node in candidates
        ]
        scored_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        best_score, _, best_node = scored_candidates[0]
        return best_node if best_score > 0 else body

    def _score_candidate(self, node: _HtmlNode) -> int:
        score = 0
        text_length = self._visible_text_length(node)
        if node.tag == "main":
            score += 120
        elif node.tag == "article":
            score += 100
        elif node.tag == "section":
            score += 60
        elif node.tag == "body":
            score += 20

        attr_tokens = self._collect_attr_tokens(node)
        score += sum(35 for token in attr_tokens if token in self.POSITIVE_ATTR_TOKENS)
        score -= sum(80 for token in attr_tokens if token in self.NEGATIVE_ATTR_TOKENS)
        score += min(120, text_length // 80)
        if self._link_text_length(node) > max(40, text_length * 0.6):
            score -= 60
        return score

    def _render_node(self, node: _HtmlNode, lines: List[str], section_depth: int, list_depth: int) -> None:
        if self._is_noise_node(node):
            return

        if node.tag in {"article", "section"}:
            structure_label = self._extract_structure_label(node)
            if structure_label:
                heading_level = min(6, section_depth + 2)
                self._append_line(lines, f"{'#' * heading_level} {structure_label}")
            for child in node.children:
                self._render_node(child, lines, section_depth + 1, list_depth)
            self._append_blank(lines)
            return

        if node.tag in self.HEADING_LEVELS:
            heading_text = self._collect_inline_text(node)
            if heading_text:
                self._append_line(lines, f"{'#' * self.HEADING_LEVELS[node.tag]} {heading_text}")
            return

        if node.tag in {"ul", "ol"}:
            ordered = node.tag == "ol"
            item_index = 1
            for child in node.children:
                if child.tag != "li":
                    continue
                prefix = f"{item_index}. " if ordered else "- "
                self._render_list_item(child, lines, prefix, list_depth)
                item_index += 1
            self._append_blank(lines)
            return

        if node.tag == "table":
            # 兼容 table > tbody > tr / thead > tr 等常见层级，同时避免误抓取嵌套表格行。
            for row in self._iter_table_rows(node):
                cells = [self._collect_inline_text(cell) for cell in row.children if cell.tag in {"td", "th"}]
                if any(cells):
                    self._append_line(lines, " | ".join(cell for cell in cells if cell))
            self._append_blank(lines)
            return

        if node.tag in {"p", "blockquote", "pre"}:
            paragraph = self._collect_inline_text(node, preserve_line_breaks=node.tag == "pre")
            if paragraph:
                self._append_line(lines, paragraph)
            return

        direct_text = _normalize_inline_text(" ".join(node.text_parts))
        if direct_text and not any(child.tag in {"p", "ul", "ol", "table", *self.HEADING_LEVELS.keys()} for child in node.children):
            self._append_line(lines, direct_text)

        for child in node.children:
            self._render_node(child, lines, section_depth, list_depth)

    def _render_list_item(self, node: _HtmlNode, lines: List[str], prefix: str, list_depth: int) -> None:
        inline_parts: List[str] = []
        for child in node.children:
            if child.tag in {"ul", "ol"}:
                continue
            rendered = self._collect_inline_text(child)
            if rendered:
                inline_parts.append(rendered)

        if node.text_parts:
            inline_parts.insert(0, _normalize_inline_text(" ".join(node.text_parts)))

        inline_text = _normalize_inline_text(" ".join(part for part in inline_parts if part))
        if inline_text:
            indent = "  " * list_depth
            self._append_line(lines, f"{indent}{prefix}{inline_text}")

        for child in node.children:
            if child.tag in {"ul", "ol"}:
                self._render_node(child, lines, section_depth=0, list_depth=list_depth + 1)

    def _iter_table_rows(self, table_node: _HtmlNode):
        for candidate in self._walk(table_node):
            if candidate.tag != "tr":
                continue
            parent = candidate.parent
            nearest_table: Optional[_HtmlNode] = None
            while parent is not None:
                if parent.tag == "table":
                    nearest_table = parent
                    break
                parent = parent.parent
            if nearest_table is table_node:
                yield candidate

    def _collect_inline_text(self, node: _HtmlNode, preserve_line_breaks: bool = False) -> str:
        pieces: List[str] = []
        if node.tag == "a":
            own_text = _normalize_inline_text(" ".join(node.text_parts), preserve_line_breaks=preserve_line_breaks)
            child_text = self._collect_children_inline_text(node, preserve_line_breaks=preserve_line_breaks)
            link_text = _normalize_inline_text(" ".join(part for part in [own_text, child_text] if part), preserve_line_breaks=preserve_line_breaks)
            href = str(node.attrs.get("href") or "").strip()
            if href and link_text and href != link_text:
                return f"{link_text} ({href})"
            return link_text

        if node.text_parts:
            separator = "\n" if preserve_line_breaks else " "
            pieces.append(separator.join(part.strip() for part in node.text_parts if part and part.strip()))

        pieces.append(self._collect_children_inline_text(node, preserve_line_breaks=preserve_line_breaks))
        joined_text = "\n".join(part for part in pieces if part) if preserve_line_breaks else " ".join(part for part in pieces if part)
        return _normalize_inline_text(joined_text, preserve_line_breaks=preserve_line_breaks)

    def _collect_children_inline_text(self, node: _HtmlNode, preserve_line_breaks: bool = False) -> str:
        parts: List[str] = []
        for child in node.children:
            if self._is_noise_node(child):
                continue
            if child.tag in {"ul", "ol", "table", "article", "section"}:
                continue
            if child.tag == "br":
                parts.append("\n" if preserve_line_breaks else " ")
                continue
            parts.append(self._collect_inline_text(child, preserve_line_breaks=preserve_line_breaks))
        joined_text = "\n".join(part for part in parts if part) if preserve_line_breaks else " ".join(part for part in parts if part)
        return _normalize_inline_text(joined_text, preserve_line_breaks=preserve_line_breaks)

    def _is_noise_node(self, node: _HtmlNode) -> bool:
        if node.tag in self.NOISE_TAGS:
            return True
        if node.tag in {"main", "article"}:
            return False
        attr_tokens = self._collect_attr_tokens(node)
        if any(token in self.POSITIVE_ATTR_TOKENS for token in attr_tokens):
            return False
        return any(token in self.NEGATIVE_ATTR_TOKENS for token in attr_tokens)

    def _collect_attr_tokens(self, node: _HtmlNode) -> set[str]:
        combined = " ".join(
            str(node.attrs.get(key) or "")
            for key in ("class", "id", "role", "aria-label", "title")
        ).lower()
        return {token for token in re.split(r"[^a-z0-9_-]+", combined) if token}

    def _visible_text_length(self, node: _HtmlNode) -> int:
        return len(self._collect_descendant_text(node))

    def _collect_descendant_text(self, node: _HtmlNode) -> str:
        if self._is_noise_node(node):
            return ""
        if node.tag == "a":
            return self._collect_inline_text(node)

        parts: List[str] = []
        if node.text_parts:
            parts.append(_normalize_inline_text(" ".join(node.text_parts)))
        for child in node.children:
            child_text = self._collect_descendant_text(child)
            if child_text:
                parts.append(child_text)
        return _normalize_inline_text(" ".join(parts))

    def _link_text_length(self, node: _HtmlNode) -> int:
        total = 0
        for child in self._walk(node):
            if child.tag == "a":
                total += len(self._collect_children_inline_text(child))
        return total

    def _walk(self, node: _HtmlNode):
        yield node
        for child in node.children:
            yield from self._walk(child)

    def _find_first(self, node: _HtmlNode, tag: str) -> Optional[_HtmlNode]:
        for current in self._walk(node):
            if current.tag == tag:
                return current
        return None

    @staticmethod
    def _extract_structure_label(node: _HtmlNode) -> Optional[str]:
        for key in ("aria-label", "title", "data-title"):
            value = _normalize_inline_text(node.attrs.get(key, ""))
            if value:
                return value
        return None

    @staticmethod
    def _append_line(lines: List[str], line: str) -> None:
        normalized_line = str(line or "").strip()
        if normalized_line:
            lines.append(normalized_line)

    @staticmethod
    def _append_blank(lines: List[str]) -> None:
        if lines and lines[-1] != "":
            lines.append("")


def _normalize_inline_text(text: str, preserve_line_breaks: bool = False) -> str:
    normalized = str(text or "")
    normalized = re.sub(r"\s+", " ", normalized) if not preserve_line_breaks else re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _normalize_block_text(lines: List[str]) -> str:
    compact_lines: List[str] = []
    for line in lines:
        normalized_line = str(line or "").rstrip()
        if not normalized_line:
            if compact_lines and compact_lines[-1] != "":
                compact_lines.append("")
            continue
        compact_lines.append(normalized_line)
    while compact_lines and compact_lines[-1] == "":
        compact_lines.pop()
    return "\n".join(compact_lines).strip()


class HtmlParser(BaseParser):
    async def parse(self, file_path: str) -> ParsedContent:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"HTML file does not exist: {path}")

        raw_html, used_encoding = read_html_text_with_fallback(path)
        builder = _HTMLTreeBuilder()
        builder.feed(raw_html)

        extractor = _MainContentExtractor()
        text, content_root_tag, blocks = extractor.extract(builder.root)
        title = builder.get_title()

        metadata = {
            "parser": "html_dom_main_content",
            "title": title,
            "content_root_tag": content_root_tag,
            "encoding": used_encoding,
            "char_count": len(text),
            "has_text": bool(text),
            "empty_content": not bool(text),
        }
        return ParsedContent(text=text, metadata=metadata, blocks=blocks or None)

    def supports(self, file_extension: str) -> bool:
        return file_extension.lower() in [".html", ".htm"]

    def get_supported_extensions(self) -> List[str]:
        return [".html", ".htm"]
