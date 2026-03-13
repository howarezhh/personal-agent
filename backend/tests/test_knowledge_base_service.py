from datetime import datetime, timezone
from types import SimpleNamespace

from backend.services.knowledge_base_service import (
    build_chunk_vector_metadata,
    format_file_as_document,
    get_upload_dir,
)


def test_get_upload_dir_supports_knowledge_base_id():
    upload_dir = get_upload_dir("user-1", knowledge_base_id="kb-1")

    normalized = upload_dir.replace("\\", "/")
    assert normalized.endswith("uploads/user-1/knowledge/kb-1")


def test_get_upload_dir_prefers_knowledge_base_id_over_conversation_id():
    upload_dir = get_upload_dir("user-1", conversation_id="conv-1", knowledge_base_id="kb-1")

    normalized = upload_dir.replace("\\", "/")
    assert normalized.endswith("uploads/user-1/knowledge/kb-1")


def test_format_file_as_document_uses_only_file_name_field():
    file_record = SimpleNamespace(
        file_id="doc-1",
        original_filename="policy.pdf",
        file_type=SimpleNamespace(value="pdf"),
        file_size=128,
        chunk_count=3,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        processing_status=SimpleNamespace(value="completed"),
        user_id="user-1",
        metadata={"knowledge_base_id": "kb-1", "knowledge_base_name": "默认知识库"},
    )

    document = format_file_as_document(file_record)

    assert document["file_name"] == "policy.pdf"
    assert "filename" not in document


def test_build_chunk_vector_metadata_uses_only_file_name_field():
    file_record = SimpleNamespace(
        file_id="doc-1",
        original_filename="policy.pdf",
        file_type=SimpleNamespace(value="pdf"),
        user_id="user-1",
        conversation_id=None,
        metadata={"knowledge_base_id": "kb-1"},
    )
    chunk = SimpleNamespace(chunk_id="chunk-1", chunk_index=0, page_number=2)

    metadata = build_chunk_vector_metadata(file_record, chunk)

    assert metadata["file_name"] == "policy.pdf"
    assert metadata["source"] == "policy.pdf"
    assert "filename" not in metadata
