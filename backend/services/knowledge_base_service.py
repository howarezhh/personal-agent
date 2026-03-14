"""知识库文件管理与向量元数据公共逻辑。"""

from __future__ import annotations

import os
import json
from typing import Any, Dict, List, Optional

from backend.core.config_manager import get_config_manager
from backend.database.repositories.file_chunk_repository import get_file_chunk_repository
from backend.models.file import File as StoredFile
from backend.models.file import FileChunk, FileType
from backend.utils.logger import get_logger


logger = get_logger(__name__)


FILE_TYPE_MAP: Dict[str, FileType] = {
    ".pdf": FileType.PDF,
    ".docx": FileType.DOCX,
    ".xlsx": FileType.XLSX,
    ".xls": FileType.XLSX,
    ".csv": FileType.TEXT,
    ".tsv": FileType.TEXT,
    ".txt": FileType.TEXT,
    ".log": FileType.TEXT,
    ".rst": FileType.TEXT,
    ".ini": FileType.TEXT,
    ".conf": FileType.TEXT,
    ".env": FileType.TEXT,
    ".properties": FileType.TEXT,
    ".gitignore": FileType.TEXT,
    ".toml": FileType.TEXT,
    ".md": FileType.MARKDOWN,
    ".markdown": FileType.MARKDOWN,
    ".json": FileType.JSON,
    ".xml": FileType.XML,
    ".yaml": FileType.CODE,
    ".yml": FileType.CODE,
    ".py": FileType.CODE,
    ".js": FileType.CODE,
    ".ts": FileType.CODE,
    ".tsx": FileType.CODE,
    ".jsx": FileType.CODE,
    ".java": FileType.CODE,
    ".cpp": FileType.CODE,
    ".c": FileType.CODE,
    ".h": FileType.CODE,
    ".hpp": FileType.CODE,
    ".go": FileType.CODE,
    ".rs": FileType.CODE,
    ".sh": FileType.CODE,
    ".bash": FileType.CODE,
    ".bat": FileType.CODE,
    ".ps1": FileType.CODE,
    ".sql": FileType.CODE,
    ".html": FileType.CODE,
    ".css": FileType.CODE,
    ".scss": FileType.CODE,
    ".less": FileType.CODE,
    ".vue": FileType.CODE,
}

MAX_FILE_SIZE = 50 * 1024 * 1024


def get_file_type(filename: str) -> FileType:
    """根据文件名推断内部文件类型。"""
    ext = os.path.splitext(filename)[1].lower()
    return FILE_TYPE_MAP.get(ext, FileType.OTHER)


def get_upload_dir(
    user_id: str,
    conversation_id: Optional[str] = None,
    knowledge_base_id: Optional[str] = None,
) -> str:
    """获取文件上传目录。"""
    config_manager = get_config_manager()
    base_dir = config_manager.get("business.file_upload.upload_directory", "uploads")

    if knowledge_base_id:
        upload_dir = os.path.join(base_dir, user_id, "knowledge", knowledge_base_id)
    elif conversation_id:
        upload_dir = os.path.join(base_dir, user_id, conversation_id)
    else:
        upload_dir = os.path.join(base_dir, user_id, "general")

    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def format_file_as_document(file_record: StoredFile) -> Dict[str, Any]:
    """将文件记录映射为知识库文档结构。"""
    metadata = file_record.metadata or {}
    created_at = file_record.created_at.isoformat() if file_record.created_at else None
    updated_at = file_record.updated_at.isoformat() if file_record.updated_at else None

    return {
        "document_id": file_record.file_id,
        "file_name": file_record.original_filename,
        "file_type": file_record.file_type.value if hasattr(file_record.file_type, "value") else str(file_record.file_type),
        "file_size": file_record.file_size,
        "chunk_count": file_record.chunk_count,
        "upload_time": created_at,
        "created_at": created_at,
        "updated_at": updated_at,
        "status": file_record.processing_status.value if hasattr(file_record.processing_status, "value") else str(file_record.processing_status),
        "processing_stage": metadata.get("processing_stage"),
        "processing_progress": metadata.get("processing_progress"),
        "error_message": getattr(file_record, "error_message", None),
        "user_id": file_record.user_id,
        "knowledge_base_id": metadata.get("knowledge_base_id"),
        "knowledge_base_name": metadata.get("knowledge_base_name"),
        "metadata": metadata,
    }


def build_chunk_vector_metadata(file_record: StoredFile, chunk: FileChunk) -> Dict[str, Any]:
    """构建统一的向量检索元数据。"""
    file_metadata = dict(file_record.metadata or {})
    payload: Dict[str, Any] = {
        "file_id": file_record.file_id,
        "chunk_id": chunk.chunk_id,
        "chunk_index": chunk.chunk_index,
        "user_id": file_record.user_id,
        "conversation_id": file_record.conversation_id,
        "file_name": file_record.original_filename,
        "original_filename": file_record.original_filename,
        "file_type": file_record.file_type.value if hasattr(file_record.file_type, "value") else str(file_record.file_type),
        "source": file_record.original_filename,
        "page_number": chunk.page_number if chunk.page_number is not None else 0,
    }
    payload.update(file_metadata)

    if file_metadata.get("knowledge_managed"):
        payload["document_id"] = file_record.file_id

    return _sanitize_vector_metadata(payload)


def _sanitize_vector_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """清洗向量数据库 metadata，移除或转换 Chroma 不支持的值。"""
    sanitized: Dict[str, Any] = {}

    for key, value in metadata.items():
        if value is None:
            continue

        if isinstance(value, (str, bool, int, float)):
            sanitized[key] = value
            continue

        if hasattr(value, "isoformat"):
            sanitized[key] = value.isoformat()
            continue

        if isinstance(value, (dict, list, tuple, set)):
            sanitized[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
            continue

        sanitized[key] = str(value)

    return sanitized


def delete_file_knowledge_data(
    file_id: str,
    *,
    chunk_repo=None,
    vector_store=None,
    log=None,
) -> Dict[str, Any]:
    """删除文件关联的向量数据和文本分块。"""
    active_logger = log or logger
    active_chunk_repo = chunk_repo or get_file_chunk_repository()
    chunks = active_chunk_repo.get_chunks_by_file_id(file_id, limit=None)

    vector_ids = [chunk.vector_id or chunk.chunk_id for chunk in chunks if (chunk.vector_id or chunk.chunk_id)]
    deleted_vectors = 0

    if vector_ids and vector_store is not None:
        success = vector_store.delete_documents(ids=vector_ids)
        if not success:
            raise RuntimeError(f"删除文件 {file_id} 的向量数据失败")
        deleted_vectors = len(vector_ids)

    deleted_chunks = 0
    if chunks:
        deleted_chunks = active_chunk_repo.delete_chunks_by_file_id(file_id)

    active_logger.info(
        f"知识库数据清理完成: file_id={file_id}, deleted_chunks={deleted_chunks}, deleted_vectors={deleted_vectors}"
    )
    return {
        "chunk_count": deleted_chunks,
        "vector_count": deleted_vectors,
        "chunk_ids": [chunk.chunk_id for chunk in chunks],
        "vector_ids": vector_ids,
    }


def is_knowledge_managed_file(file_record: StoredFile) -> bool:
    """判断文件是否属于知识库管理页。"""
    metadata = file_record.metadata or {}
    return bool(metadata.get("knowledge_managed"))
