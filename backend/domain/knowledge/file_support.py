from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from backend.core.config_manager import get_config_manager
from backend.database.repositories.file_chunk_repository import get_file_chunk_repository
from backend.models.file import File, FileChunk, FileType
from backend.utils.logger import get_logger

logger = get_logger(__name__)


_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp",
    ".go", ".rs", ".rb", ".php", ".cs", ".swift", ".kt", ".kts", ".scala", ".sh", ".bash", ".zsh",
    ".bat", ".ps1", ".sql", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env",
}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}


def _file_upload_config() -> dict[str, Any]:
    config = get_config_manager().get_business_config("file_upload", {})
    return config if isinstance(config, dict) else {}


MAX_FILE_SIZE = int(_file_upload_config().get("max_file_size_mb", 50) or 50) * 1024 * 1024


def get_upload_dir(*, user_id: str, knowledge_base_id: str | None) -> str:
    upload_root = str(_file_upload_config().get("upload_directory", "./data/uploads") or "./data/uploads")
    target = Path(upload_root) / "knowledge" / str(user_id)
    if knowledge_base_id:
        target = target / str(knowledge_base_id)
    return str(target)


def get_file_type(filename: str | None) -> FileType:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".pdf":
        return FileType.PDF
    if suffix == ".docx":
        return FileType.DOCX
    if suffix == ".pptx":
        return FileType.PPTX
    if suffix in {".xlsx", ".xls", ".csv"}:
        return FileType.XLSX
    if suffix in {".html", ".htm"}:
        return FileType.HTML
    if suffix in _IMAGE_EXTENSIONS:
        return FileType.IMAGE
    if suffix in {".txt", ".rst", ".log"}:
        return FileType.TEXT
    if suffix in {".md", ".markdown"}:
        return FileType.MARKDOWN
    if suffix == ".json":
        return FileType.JSON
    if suffix == ".xml":
        return FileType.XML
    if suffix in _CODE_EXTENSIONS:
        return FileType.CODE
    return FileType.OTHER


def is_knowledge_managed_file(file_record: File | Any) -> bool:
    metadata = getattr(file_record, "metadata", None)
    if not isinstance(metadata, dict):
        return False
    if metadata.get("knowledge_managed") is True:
        return True
    return metadata.get("uploaded_via") == "knowledge_api"


def format_file_as_document(file_record: File | Any) -> dict[str, Any]:
    metadata = dict(getattr(file_record, "metadata", {}) or {})
    file_type = getattr(file_record, "file_type", None)
    if hasattr(file_type, "value"):
        file_type = file_type.value
    document_id = getattr(file_record, "file_id", None) or metadata.get("document_id") or ""
    created_at = getattr(file_record, "created_at", None)
    updated_at = getattr(file_record, "updated_at", None)
    processed_at = getattr(file_record, "processed_at", None)
    upload_time = created_at or updated_at or processed_at
    processing_status = getattr(file_record, "processing_status", None)
    if hasattr(processing_status, "value"):
        processing_status = processing_status.value

    return {
        "document_id": str(document_id),
        "file_name": str(getattr(file_record, "original_filename", "") or ""),
        "file_type": str(file_type or "other"),
        "file_size": int(getattr(file_record, "file_size", 0) or 0),
        "chunk_count": int(getattr(file_record, "chunk_count", 0) or 0),
        "upload_time": upload_time.isoformat() if hasattr(upload_time, "isoformat") else None,
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else None,
        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else None,
        "user_id": str(getattr(file_record, "user_id", "") or ""),
        "knowledge_base_id": metadata.get("knowledge_base_id"),
        "knowledge_base_name": metadata.get("knowledge_base_name"),
        "status": str(processing_status or "completed"),
        "processing_stage": metadata.get("processing_stage"),
        "processing_progress": metadata.get("processing_progress"),
        "error_message": getattr(file_record, "error_message", None) or metadata.get("error_message"),
        "vectorized_chunk_count": int(metadata.get("vectorized_chunk_count", 0) or 0),
        "missing_vector_chunk_count": int(metadata.get("missing_vector_chunk_count", 0) or 0),
        "vectorization_status": str(metadata.get("vectorization_status", "unknown") or "unknown"),
        "can_retry_vectorization": bool(metadata.get("can_retry_vectorization", False)),
    }


def build_chunk_vector_metadata(file_record: File | Any, chunk: FileChunk | Any) -> dict[str, Any]:
    file_metadata = dict(getattr(file_record, "metadata", {}) or {})
    chunk_metadata = dict(getattr(chunk, "metadata", {}) or {})
    source_name = (
        file_metadata.get("knowledge_base_name")
        or getattr(file_record, "original_filename", None)
        or file_metadata.get("source")
        or "Unknown"
    )
    metadata = {
        "file_id": getattr(file_record, "file_id", None),
        "document_id": getattr(file_record, "file_id", None),
        "chunk_id": getattr(chunk, "chunk_id", None),
        "chunk_index": getattr(chunk, "chunk_index", None),
        "knowledge_base_id": file_metadata.get("knowledge_base_id"),
        "knowledge_base_name": file_metadata.get("knowledge_base_name"),
        "file_name": getattr(file_record, "original_filename", None),
        "original_filename": getattr(file_record, "original_filename", None),
        "source": source_name,
        "user_id": getattr(file_record, "user_id", None),
        "page_number": getattr(chunk, "page_number", None) or chunk_metadata.get("page_number"),
        "start_char": getattr(chunk, "start_char", None) or chunk_metadata.get("start_char"),
        "end_char": getattr(chunk, "end_char", None) or chunk_metadata.get("end_char"),
        "token_count": getattr(chunk, "token_count", None) or chunk_metadata.get("token_count"),
    }
    return {key: value for key, value in metadata.items() if value is not None}


def delete_file_knowledge_data(*, file_id: str, vector_store=None, log=None) -> dict[str, Any]:
    chunk_repo = get_file_chunk_repository()
    chunks = chunk_repo.get_chunks_by_file_id(file_id, limit=None)
    vector_ids = [chunk.vector_id for chunk in chunks if getattr(chunk, "vector_id", None)]
    chunk_count = len(chunks)
    vector_count = len(vector_ids)
    target_log = log or logger
    vector_delete_success = True

    if vector_store is not None:
        try:
            if vector_ids:
                vector_delete_success = bool(vector_store.delete_documents(ids=vector_ids))
            else:
                vector_delete_success = bool(vector_store.delete_documents(where={"file_id": file_id}))
        except Exception as error:
            vector_delete_success = False
            target_log.error("Failed to delete vectors for file_id=%s: %s", file_id, error, exc_info=True)

    deleted_chunk_count = chunk_repo.delete_chunks_by_file_id(file_id) if chunk_count else 0
    result = {
        "file_id": file_id,
        "chunk_count": int(deleted_chunk_count or chunk_count),
        "vector_count": vector_count,
        "vector_delete_success": vector_delete_success,
    }
    target_log.info(
        "Knowledge data cleanup completed: file_id=%s chunks=%s vectors=%s vector_delete_success=%s",
        file_id,
        result["chunk_count"],
        result["vector_count"],
        vector_delete_success,
    )
    return result
