from backend.agents.base.stream_chunk import StreamChunk


def test_stream_chunk_repr_supports_non_string_content():
    chunk = StreamChunk.create_result({"citations": [{"id": "c1"}]})

    representation = repr(chunk)

    assert "StreamChunk(type='result'" in representation
    assert "citations" in representation

