from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.contracts.async_task import AsyncTaskStatus, normalize_async_task_status
from backend.core.config_manager import get_config_manager
from backend.database.repositories.file_chunk_repository import get_file_chunk_repository
from backend.file_processors.document_registry import get_file_type_for_filename
from backend.models.file import File, FileChunk, FileType, ProcessingStatus
from backend.utils.logger import get_logger

logger = get_logger(__name__)


def _prefer_non_none(primary: Any, fallback: Any) -> Any:
    """优先保留非 None 值，避免 `0` 这类合法值被 `or` 误吞。"""
    return primary if primary is not None else fallback


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
    """统一走文档注册表，避免扩展名与 FileType 漂移。"""
    return get_file_type_for_filename(filename)


def is_knowledge_managed_file(file_record: File | Any) -> bool:
    metadata = getattr(file_record, "metadata", None)
    if not isinstance(metadata, dict):
        return False
    if metadata.get("knowledge_managed") is True:
        return True
    return metadata.get("uploaded_via") == "knowledge_api"


def _normalize_document_status(processing_status: Any, task_status: Any) -> str:
    """统一文档处理状态到前端已使用的 legacy 值域。

    文档上传/解析主链路的权威来源应为 `files.processing_status`，因为它会随着
    解析、切分、向量化、总结等阶段持续更新。`metadata.task_status` 主要用于
    任务语义补充，历史数据里可能出现未及时刷新而滞后的情况，因此这里只作为
    回退来源，避免出现“进度 100% / 处理完成，但状态仍是等待中”的展示错位。
    """

    # 先读取数据库主状态，确保上传处理链路的最终完成态不会被陈旧 metadata 覆盖。
    raw_status = processing_status.value if hasattr(processing_status, "value") else processing_status
    if raw_status is None:
        raw_status = task_status

    normalized_status = str(raw_status or "").strip().lower()
    status_mapping = {
        AsyncTaskStatus.PENDING.value: ProcessingStatus.PENDING.value,
        "queued": ProcessingStatus.PENDING.value,
        AsyncTaskStatus.RUNNING.value: ProcessingStatus.PROCESSING.value,
        ProcessingStatus.PROCESSING.value: ProcessingStatus.PROCESSING.value,
        "retrying": ProcessingStatus.PROCESSING.value,
        AsyncTaskStatus.SUCCEEDED.value: ProcessingStatus.COMPLETED.value,
        ProcessingStatus.COMPLETED.value: ProcessingStatus.COMPLETED.value,
        "success": ProcessingStatus.COMPLETED.value,
        AsyncTaskStatus.FAILED.value: ProcessingStatus.FAILED.value,
        AsyncTaskStatus.CANCELLED.value: ProcessingStatus.FAILED.value,
        AsyncTaskStatus.TIMED_OUT.value: ProcessingStatus.FAILED.value,
        ProcessingStatus.FAILED.value: ProcessingStatus.FAILED.value,
    }
    return status_mapping.get(normalized_status, ProcessingStatus.PENDING.value)


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
    # 文档状态优先使用数据库主字段 `processing_status`，防止陈旧 `task_status` 造成状态卡住。
    normalized_status = _normalize_document_status(processing_status, metadata.get("task_status"))
    normalized_vectorization_status = normalize_async_task_status(
        metadata.get("vectorization_status"),
        default=AsyncTaskStatus.PENDING,
    )

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
        "status": normalized_status,
        "processing_stage": metadata.get("processing_stage"),
        "processing_progress": metadata.get("processing_progress"),
        "error_message": getattr(file_record, "error_message", None) or metadata.get("error_message"),
        "vectorized_chunk_count": int(metadata.get("vectorized_chunk_count", 0) or 0),
        "missing_vector_chunk_count": int(metadata.get("missing_vector_chunk_count", 0) or 0),
        "vectorization_status": normalized_vectorization_status,
        "can_retry_vectorization": bool(metadata.get("can_retry_vectorization", False)),
        "idempotency_key": metadata.get("idempotency_key"),
    }


def _normalize_file_type_value(file_record: File | Any, file_metadata: dict[str, Any]) -> str:
    """统一文件类型取值，避免记录字段与文件名推断结果漂移。"""
    file_type = getattr(file_record, "file_type", None)
    if hasattr(file_type, "value"):
        file_type = file_type.value
    if not file_type:
        file_type = file_metadata.get("file_type")
    if not file_type:
        file_type = get_file_type(getattr(file_record, "original_filename", None)).value
    return str(file_type or FileType.OTHER.value)


def _infer_source_type(file_type: str, file_metadata: dict[str, Any]) -> str:
    """根据文件类型推断来源类型，和重排器的权威性规则保持一致。"""
    explicit_source_type = str(file_metadata.get("source_type") or "").strip()
    if explicit_source_type:
        return explicit_source_type

    normalized_file_type = str(file_type or "").lower()
    mapping = {
        "pdf": "document",
        "docx": "document",
        "markdown": "document",
        "md": "document",
        "text": "document",
        "txt": "document",
        "pptx": "presentation",
        "xlsx": "spreadsheet",
        "xls": "spreadsheet",
        "csv": "spreadsheet",
        "tsv": "spreadsheet",
        "json": "structured_data",
        "xml": "structured_data",
        "yaml": "structured_data",
        "yml": "structured_data",
        "code": "code",
        "html": "article",
    }
    return mapping.get(normalized_file_type, "unknown")


def _build_structured_terms_text(chunk_metadata: dict[str, Any]) -> str | None:
    """从结构化字段汇总检索辅助词，避免向量元数据缺少召回特征。"""
    values: list[str] = []
    for field in (
        "section_title",
        "section_path",
        "sheet_name",
        "symbol_name",
        "symbol_type",
        "node_name",
        "leaf_value",
        "slide_title",
        "source_region",
    ):
        value = chunk_metadata.get(field)
        if value:
            values.append(str(value))

    column_headers = chunk_metadata.get("column_headers")
    if isinstance(column_headers, list):
        values.extend(str(item) for item in column_headers if item)
    elif column_headers:
        values.append(str(column_headers))

    deduplicated: list[str] = []
    for value in values:
        normalized_value = str(value).strip()
        if normalized_value and normalized_value not in deduplicated:
            deduplicated.append(normalized_value)
    return " ".join(deduplicated) if deduplicated else None


def build_chunk_vector_metadata(file_record: File | Any, chunk: FileChunk | Any) -> dict[str, Any]:
    """构造写入向量库的 chunk 元数据。

    这里需要把切分阶段已经抽取出的结构化信息尽可能完整地透传到向量库，
    这样混合检索、精确短语匹配和重排阶段才能在同一套语料上使用一致的字段。
    """
    file_metadata = dict(getattr(file_record, "metadata", {}) or {})
    chunk_metadata = dict(getattr(chunk, "metadata", {}) or {})
    # 引用来源应优先展示具体文档名，而不是知识库名，否则前端引用会丢失真实出处。
    source_name = (
        getattr(file_record, "original_filename", None)
        or file_metadata.get("file_name")
        or file_metadata.get("original_filename")
        or file_metadata.get("source")
        or file_metadata.get("knowledge_base_name")
        or "Unknown"
    )
    normalized_file_type = _normalize_file_type_value(file_record, file_metadata)
    structured_terms = chunk_metadata.get("structured_terms") or _build_structured_terms_text(chunk_metadata)
    metadata = {
        "file_id": getattr(file_record, "file_id", None),
        "document_id": getattr(file_record, "file_id", None),
        "chunk_id": getattr(chunk, "chunk_id", None),
        "chunk_index": getattr(chunk, "chunk_index", None),
        "knowledge_base_id": file_metadata.get("knowledge_base_id"),
        "knowledge_base_name": file_metadata.get("knowledge_base_name"),
        "file_name": getattr(file_record, "original_filename", None),
        "original_filename": getattr(file_record, "original_filename", None),
        "file_type": normalized_file_type,
        "source_type": _infer_source_type(normalized_file_type, file_metadata),
        "source": source_name,
        "user_id": getattr(file_record, "user_id", None),
        "page_number": _prefer_non_none(getattr(chunk, "page_number", None), chunk_metadata.get("page_number")),
        "start_char": _prefer_non_none(getattr(chunk, "start_char", None), chunk_metadata.get("start_char")),
        "end_char": _prefer_non_none(getattr(chunk, "end_char", None), chunk_metadata.get("end_char")),
        "token_count": _prefer_non_none(getattr(chunk, "token_count", None), chunk_metadata.get("token_count")),
        # 结构化切分字段：这些字段会直接影响 hybrid retrieval、exact phrase 和 rerank 质量。
        "section_title": chunk_metadata.get("section_title"),
        "section_path": chunk_metadata.get("section_path"),
        "heading_level": chunk_metadata.get("heading_level"),
        "sheet_name": chunk_metadata.get("sheet_name"),
        "table_index": chunk_metadata.get("table_index"),
        "symbol_name": chunk_metadata.get("symbol_name"),
        "symbol_type": chunk_metadata.get("symbol_type"),
        "node_name": chunk_metadata.get("node_name"),
        "leaf_value": chunk_metadata.get("leaf_value"),
        "column_headers": chunk_metadata.get("column_headers"),
        "slide_title": chunk_metadata.get("slide_title"),
        "source_region": chunk_metadata.get("source_region"),
        "notes_included": chunk_metadata.get("notes_included"),
        "structured_terms": structured_terms,
        "source_tag": chunk_metadata.get("source_tag"),
        "block_type": chunk_metadata.get("block_type"),
    }
    return {key: value for key, value in metadata.items() if value is not None}


def delete_file_knowledge_data(*, file_id: str, chunk_repo=None, vector_store=None, log=None) -> dict[str, Any]:
    chunk_repo = chunk_repo or get_file_chunk_repository()
    chunks = chunk_repo.get_chunks_by_file_id(file_id, limit=None)
    vector_ids = [chunk.vector_id for chunk in chunks if getattr(chunk, "vector_id", None)]
    chunk_count = len(chunks)
    vector_count = len(vector_ids)
    target_log = log or logger
    vector_delete_success = True
    vector_delete_attempted = False

    if vector_store is not None:
        try:
            vector_delete_attempted = True
            if vector_ids:
                vector_delete_success = bool(vector_store.delete_documents(ids=vector_ids))
            else:
                vector_delete_success = bool(vector_store.delete_documents(where={"file_id": file_id}))
        except Exception as error:
            vector_delete_success = False
            target_log.error("Failed to delete vectors for file_id=%s: %s", file_id, error, exc_info=True)

    # 旧向量删除失败时，保留旧 chunk 记录并中断后续重建，避免出现“旧向量 + 新 chunk”混合态。
    if vector_delete_attempted and not vector_delete_success:
        result = {
            "file_id": file_id,
            "chunk_count": chunk_count,
            "vector_count": vector_count,
            "vector_delete_success": False,
            "vector_delete_attempted": True,
        }
        target_log.warning(
            "Knowledge cleanup aborted because vector deletion failed: file_id=%s chunks=%s vectors=%s",
            file_id,
            chunk_count,
            vector_count,
        )
        return result

    deleted_chunk_count = chunk_repo.delete_chunks_by_file_id(file_id) if chunk_count else 0
    result = {
        "file_id": file_id,
        "chunk_count": int(deleted_chunk_count or chunk_count),
        "vector_count": vector_count,
        "vector_delete_success": vector_delete_success,
        "vector_delete_attempted": vector_delete_attempted,
    }
    target_log.info(
        "Knowledge data cleanup completed: file_id=%s chunks=%s vectors=%s vector_delete_success=%s",
        file_id,
        result["chunk_count"],
        result["vector_count"],
        vector_delete_success,
    )
    return result
