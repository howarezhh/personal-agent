from evaluation.chunkers import FixedWindowChunker, ParagraphChunker


def test_fixed_window_chunker_preserves_overlap():
    chunker = FixedWindowChunker(chunk_size=5, chunk_overlap=2)
    chunks = chunker.split("abcdefghij", document_id="doc-1")

    assert [chunk.text for chunk in chunks] == ["abcde", "defgh", "ghij"]
    assert chunks[1].metadata["start_char"] == 3
    assert chunks[1].metadata["end_char"] == 8


def test_paragraph_chunker_keeps_paragraph_boundaries_when_possible():
    chunker = ParagraphChunker(chunk_size=12, chunk_overlap=0)
    text = "第一段第一句。\n\n第二段第二句。\n\n第三段第三句。"

    chunks = chunker.split(text, document_id="doc-1")

    assert len(chunks) >= 2
    assert chunks[0].text.startswith("第一段第一句")
    assert all(chunk.metadata["chunking_strategy"].startswith("paragraph_") for chunk in chunks)
