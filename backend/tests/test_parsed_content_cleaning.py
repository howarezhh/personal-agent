import pytest

from backend.file_processors.parsers.base_parser import BaseParser, ParsedContent
from backend.file_processors.parsers.excel_text_parser import TextParser


class DummyPaginatedParser(BaseParser):
    async def parse(self, file_path: str) -> ParsedContent:
        return ParsedContent(
            text="",
            metadata={"title": "\ufeffProject\u00a0Guide", "author": "A\x00lice"},
            pages=[
                {
                    "page_number": 1,
                    "text": "Project Guide\nPage 1\nThis is a bro-\nken paragraph line\n1",
                },
                {
                    "page_number": 2,
                    "text": "Project Guide\nPage 2\nAnother paragraph\ncontinues here\n2",
                },
            ],
            tables=[{"rows": [["A\x00", " B "]]}],
        )

    def supports(self, file_extension: str) -> bool:
        return True


@pytest.mark.asyncio
async def test_safe_parse_applies_shared_cleaning_to_paginated_documents(tmp_path):
    parser = DummyPaginatedParser()
    source = tmp_path / "sample.pdf"
    source.write_text("placeholder", encoding="utf-8")

    result = await parser.safe_parse(str(source))

    assert result["success"] is True
    content = result["content"]
    assert content.metadata["title"] == "Project Guide"
    assert content.metadata["author"] == "Alice"
    assert "Project Guide" not in content.text
    assert "Page 1" not in content.text
    assert "broken paragraph line" in content.text
    assert "Another paragraph continues here" in content.text
    assert content.pages[0]["text"] == "This is a broken paragraph line"
    assert content.pages[1]["text"] == "Another paragraph continues here"
    assert content.tables[0]["rows"][0] == ["A", "B"]


@pytest.mark.asyncio
async def test_text_parser_preserves_structured_file_line_boundaries(tmp_path):
    parser = TextParser()
    source = tmp_path / "demo.py"
    source.write_text("\ufeffdef demo():\n\treturn 1\n", encoding="utf-8")

    result = await parser.safe_parse(str(source))

    assert result["success"] is True
    content = result["content"]
    assert content.text == "def demo():\n    return 1"
    assert "def demo(): return 1" not in content.text
