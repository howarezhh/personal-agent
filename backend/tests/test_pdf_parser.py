import asyncio
import sys
import types

import pytest

from backend.file_processors.parsers.base_parser import ParsedContent
from backend.file_processors.parsers.pdf_parser import PDFParser


@pytest.mark.asyncio
async def test_pdfplumber_wrapper_offloads_blocking_work_to_thread(tmp_path, monkeypatch):
    parser = PDFParser()
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    captured: dict[str, object] = {}

    async def fake_to_thread(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return ParsedContent(text="ok", metadata={"parser": "pdfplumber"}, pages=[])

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    result = await parser._parse_with_pdfplumber(pdf_path)

    assert result.text == "ok"
    assert captured["func"] == parser._parse_with_pdfplumber_sync
    assert captured["args"] == (pdf_path,)


@pytest.mark.asyncio
async def test_parse_rejects_missing_pdf_path():
    parser = PDFParser()

    with pytest.raises(FileNotFoundError, match="does not exist"):
        await parser.parse("missing-file.pdf")


@pytest.mark.asyncio
async def test_parse_returns_empty_text_metadata_for_empty_pdf(tmp_path, monkeypatch):
    parser = PDFParser()
    pdf_path = tmp_path / "empty.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    class FakePage:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class FakePDF:
        def __init__(self):
            self.pages = [FakePage(None), FakePage("\x00")]
            self.metadata = {
                "Title": b"bad\xfftitle",
                "Author": "Auth\x00or",
                "Subject": None,
                "Creator": b"Cre\xffator",
            }

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

    def fake_open(file_obj):
        assert not file_obj.closed
        return FakePDF()

    monkeypatch.setitem(sys.modules, "pdfplumber", types.SimpleNamespace(open=fake_open))

    result = await parser.parse(str(pdf_path))

    assert result.text == ""
    assert result.pages == []
    assert result.metadata["parser"] == "pdfplumber"
    assert result.metadata["total_pages"] == 2
    assert result.metadata["has_text"] is False
    assert result.metadata["empty_content"] is True
    assert result.metadata["title"] == "bad�title"
    assert result.metadata["author"] == "Author"
    assert result.metadata["subject"] == ""
    assert result.metadata["creator"] == "Cre�ator"


@pytest.mark.asyncio
async def test_parse_falls_back_to_pypdf2_when_pdfplumber_missing(tmp_path, monkeypatch):
    parser = PDFParser()
    pdf_path = tmp_path / "fallback.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    async def raise_import_error(_file_path):
        raise ImportError("pdfplumber missing")

    async def parse_with_pypdf2(_file_path):
        return ParsedContent(text="fallback", metadata={"parser": "PyPDF2"}, pages=[])

    monkeypatch.setattr(parser, "_parse_with_pdfplumber", raise_import_error)
    monkeypatch.setattr(parser, "_parse_with_pypdf2", parse_with_pypdf2)

    result = await parser.parse(str(pdf_path))

    assert result.text == "fallback"
    assert result.metadata["parser"] == "PyPDF2"
