# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Request, UploadFile, status

from backend.api.app_services import get_knowledge_management_application_service
from backend.api.dependencies import get_current_user_id
from backend.contracts.api.knowledge import (
    BatchUploadItemResponse,
    BatchUploadResponse,
    DocumentInfo,
    DocumentListResponse,
    FullVectorRebuildResponse,
    FullVectorRebuildTaskResponse,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseListResponse,
    KnowledgeBaseResponse,
    KnowledgeSearchItem,
    KnowledgeSearchResponse,
    SearchRequest,
    VectorRebuildItem,
    VectorRebuildRequest,
    VectorRebuildResponse,
)
from backend.contracts.errors import AppException, ErrorCode, bad_request, forbidden, internal_server_error, not_found
from backend.contracts.responses import MessageResponse, SuccessResponse
from backend.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


def _request_id(request: Request) -> str | None:
    return getattr(getattr(request, "state", None), "request_id", None)


def _build_vector_rebuild_items(details: list[dict[str, Any]]) -> list[VectorRebuildItem]:
    return [
        VectorRebuildItem(
            document_id=item["document_id"],
            file_name=item["file_name"],
            missing_before=item["missing_before"],
            vectorized_now=item["vectorized_now"],
            missing_after=item["missing_after"],
            success=item["success"],
            error=item.get("error"),
        )
        for item in details
    ]


def _build_vector_rebuild_response(result: dict[str, Any]) -> VectorRebuildResponse:
    return VectorRebuildResponse(
        total_documents=result["total_documents"],
        processed_documents=result["processed_documents"],
        succeeded_documents=result["succeeded_documents"],
        failed_documents=result["failed_documents"],
        total_missing_chunks_before=result["total_missing_chunks_before"],
        total_vectorized_chunks_now=result["total_vectorized_chunks_now"],
        total_missing_chunks_after=result["total_missing_chunks_after"],
        details=_build_vector_rebuild_items(result.get("details", [])),
    )


def _build_full_vector_rebuild_response(result: dict[str, Any]) -> FullVectorRebuildResponse:
    return FullVectorRebuildResponse(
        **_build_vector_rebuild_response(result).model_dump(),
        reset_collection=result.get("reset_collection", False),
        target_dimension=result.get("target_dimension", 512),
        error=result.get("error"),
    )


def _build_full_vector_rebuild_task_response(task: dict[str, Any]) -> FullVectorRebuildTaskResponse:
    return FullVectorRebuildTaskResponse(
        **_build_full_vector_rebuild_response(task).model_dump(),
        task_id=task["task_id"],
        status=task.get("status", "pending"),
        scope=task.get("scope", "all_knowledge_bases"),
        knowledge_base_id=task.get("knowledge_base_id"),
        current_document_id=task.get("current_document_id"),
        current_file_name=task.get("current_file_name"),
        created_at=task["created_at"],
        updated_at=task.get("updated_at"),
        started_at=task.get("started_at"),
        finished_at=task.get("finished_at"),
    )


def _build_batch_upload_response(result: dict[str, Any]) -> BatchUploadResponse:
    return BatchUploadResponse(
        total=result["total"],
        success_count=result["success_count"],
        failed_count=result["failed_count"],
        results=[
            BatchUploadItemResponse(
                file_name=item["file_name"],
                success=item["success"],
                document=DocumentInfo(**item["document"]) if item.get("document") else None,
                error=item.get("error"),
            )
            for item in result["results"]
        ],
    )


def _build_search_response(result: dict[str, Any]) -> KnowledgeSearchResponse:
    return KnowledgeSearchResponse(
        query=result["query"],
        knowledge_base_id=result.get("knowledge_base_id"),
        results=[KnowledgeSearchItem(**item) for item in result.get("results", [])],
        total=result["total"],
    )


@router.get("/bases", response_model=SuccessResponse[KnowledgeBaseListResponse])
async def get_knowledge_bases(user_id: str = Depends(get_current_user_id)):
    result = get_knowledge_management_application_service().list_knowledge_bases(user_id=user_id)
    return SuccessResponse.create(
        data=KnowledgeBaseListResponse(
            knowledge_bases=[KnowledgeBaseResponse(**item) for item in result["knowledge_bases"]],
            total=result["total"],
        )
    )


@router.post("/bases", response_model=SuccessResponse[KnowledgeBaseResponse], status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(payload: KnowledgeBaseCreateRequest, user_id: str = Depends(get_current_user_id)):
    try:
        knowledge_base = get_knowledge_management_application_service().create_knowledge_base(
            user_id=user_id,
            name=payload.name,
            description=payload.description,
        )
        return SuccessResponse.create(
            data=KnowledgeBaseResponse(**knowledge_base),
            message="Knowledge base created successfully",
            code=status.HTTP_201_CREATED,
        )
    except ValueError as error:
        raise bad_request(str(error), error_code=ErrorCode.SYSTEM_VALIDATION_ERROR, error="KnowledgeValidationError") from error
    except Exception as error:
        logger.error("Create knowledge base failed: %s", error, exc_info=True)
        raise internal_server_error("创建知识库失败") from error


@router.delete("/bases/{knowledge_base_id}", response_model=MessageResponse)
async def delete_knowledge_base(
    knowledge_base_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    try:
        knowledge_base = get_knowledge_management_application_service().delete_knowledge_base(
            knowledge_base_id=knowledge_base_id,
            user_id=user_id,
            request_id=_request_id(request),
        )
        return MessageResponse.create(message=f"Knowledge base '{knowledge_base['name']}' deleted successfully")
    except FileNotFoundError as error:
        raise not_found(str(error), error_code=ErrorCode.KNOWLEDGE_BASE_NOT_FOUND, error="KnowledgeNotFound") from error
    except PermissionError as error:
        raise forbidden(str(error), error_code=ErrorCode.SYSTEM_FORBIDDEN, error="KnowledgeAccessDenied") from error
    except Exception as error:
        logger.error("Delete knowledge base failed: %s", error, exc_info=True)
        raise internal_server_error("删除知识库失败") from error


@router.post("/upload", response_model=SuccessResponse[DocumentInfo])
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="待上传的知识库文档"),
    knowledge_base_id: Optional[str] = Form(default=None, description="所属知识库 ID"),
    user_id: str = Depends(get_current_user_id),
):
    try:
        service = get_knowledge_management_application_service()
        upload_result = await service.create_document_upload(
            user_id=user_id,
            upload_file=file,
            knowledge_base_id=knowledge_base_id,
            request_id=_request_id(request),
        )
        background_tasks.add_task(service.process_uploaded_document, upload_result.file_id, _request_id(request))
        return SuccessResponse.create(
            data=DocumentInfo(**upload_result.document),
            message="Document upload accepted",
        )
    except AppException:
        raise
    except ValueError as error:
        raise bad_request(str(error), error_code=ErrorCode.SYSTEM_VALIDATION_ERROR, error="KnowledgeValidationError") from error
    except FileNotFoundError as error:
        raise not_found(str(error), error_code=ErrorCode.KNOWLEDGE_BASE_NOT_FOUND, error="KnowledgeNotFound") from error
    except Exception as error:
        logger.error("Upload document failed: %s", error, exc_info=True)
        raise internal_server_error("上传文档失败") from error


@router.post("/upload/batch", response_model=SuccessResponse[BatchUploadResponse])
async def upload_documents_batch(
    request: Request,
    files: list[UploadFile] = File(..., description="待上传的知识库文档列表"),
    knowledge_base_id: Optional[str] = Form(default=None, description="所属知识库 ID"),
    user_id: str = Depends(get_current_user_id),
):
    if not files:
        raise bad_request(
            "请至少上传一个文件",
            error_code=ErrorCode.SYSTEM_VALIDATION_ERROR,
            error="KnowledgeUploadValidationError",
        )

    try:
        result = await get_knowledge_management_application_service().upload_documents_batch(
            user_id=user_id,
            upload_files=files,
            knowledge_base_id=knowledge_base_id,
            request_id=_request_id(request),
        )
        return SuccessResponse.create(
            data=_build_batch_upload_response(result),
            message="Batch document upload completed",
        )
    except AppException:
        raise
    except ValueError as error:
        raise bad_request(str(error), error_code=ErrorCode.SYSTEM_VALIDATION_ERROR, error="KnowledgeValidationError") from error
    except FileNotFoundError as error:
        raise not_found(str(error), error_code=ErrorCode.KNOWLEDGE_BASE_NOT_FOUND, error="KnowledgeNotFound") from error
    except Exception as error:
        logger.error("Batch upload document failed: %s", error, exc_info=True)
        raise internal_server_error("批量上传文档失败") from error


@router.get("/documents/{document_id}/status", response_model=SuccessResponse[DocumentInfo])
async def get_document_status(
    document_id: str,
    user_id: str = Depends(get_current_user_id),
):
    try:
        document = get_knowledge_management_application_service().get_document_status(
            document_id=document_id,
            user_id=user_id,
        )
        return SuccessResponse.create(data=DocumentInfo(**document))
    except FileNotFoundError as error:
        raise not_found(str(error), error_code=ErrorCode.KNOWLEDGE_BASE_NOT_FOUND, error="KnowledgeNotFound") from error
    except PermissionError as error:
        raise forbidden(str(error), error_code=ErrorCode.SYSTEM_FORBIDDEN, error="KnowledgeAccessDenied") from error
    except Exception as error:
        logger.error("Get document status failed: %s", error, exc_info=True)
        raise internal_server_error("获取文档状态失败") from error


@router.get("/documents", response_model=SuccessResponse[DocumentListResponse])
async def get_documents(
    knowledge_base_id: Optional[str] = Query(default=None, description="按知识库过滤文档"),
    user_id: str = Depends(get_current_user_id),
):
    try:
        result = get_knowledge_management_application_service().list_documents(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
        )
        return SuccessResponse.create(
            data=DocumentListResponse(
                documents=[DocumentInfo(**document) for document in result["documents"]],
                total=result["total"],
            )
        )
    except FileNotFoundError as error:
        raise not_found(str(error), error_code=ErrorCode.KNOWLEDGE_BASE_NOT_FOUND, error="KnowledgeNotFound") from error
    except Exception as error:
        logger.error("Get knowledge documents failed: %s", error, exc_info=True)
        raise internal_server_error("获取知识库文档失败") from error


@router.delete("/documents/{document_id}", response_model=MessageResponse)
async def delete_document(
    document_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    try:
        cleanup_result = get_knowledge_management_application_service().delete_document(
            document_id=document_id,
            user_id=user_id,
            request_id=_request_id(request),
        )
        return MessageResponse.create(
            message=f"Document deleted successfully ({cleanup_result['chunk_count']} chunks removed)",
            code=200,
        )
    except FileNotFoundError as error:
        raise not_found(str(error), error_code=ErrorCode.KNOWLEDGE_BASE_NOT_FOUND, error="KnowledgeNotFound") from error
    except PermissionError as error:
        raise forbidden(str(error), error_code=ErrorCode.SYSTEM_FORBIDDEN, error="KnowledgeAccessDenied") from error
    except Exception as error:
        logger.error("Delete document failed: %s", error, exc_info=True)
        raise internal_server_error("删除文档失败") from error


@router.post("/rebuild-vectors", response_model=SuccessResponse[VectorRebuildResponse])
async def rebuild_vectors(
    payload: VectorRebuildRequest,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    try:
        result = get_knowledge_management_application_service().retry_pending_vectorizations(
            user_id=user_id,
            knowledge_base_id=payload.knowledge_base_id,
            request_id=_request_id(request),
        )
        return SuccessResponse.create(
            data=_build_vector_rebuild_response(result),
            message="Vector rebuild completed",
        )
    except AppException:
        raise
    except PermissionError as error:
        raise forbidden(str(error), error_code=ErrorCode.SYSTEM_FORBIDDEN, error="KnowledgeAccessDenied") from error
    except FileNotFoundError as error:
        raise not_found(str(error), error_code=ErrorCode.KNOWLEDGE_BASE_NOT_FOUND, error="KnowledgeNotFound") from error
    except Exception as error:
        logger.error("Rebuild vectors failed: %s", error, exc_info=True)
        raise internal_server_error("重建向量失败") from error


@router.post(
    "/rebuild-vectors/full/tasks",
    response_model=SuccessResponse[FullVectorRebuildTaskResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_full_rebuild_vectors_task(
    payload: VectorRebuildRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    try:
        service = get_knowledge_management_application_service()
        task_result = service.start_full_vector_rebuild_task(
            user_id=user_id,
            knowledge_base_id=payload.knowledge_base_id,
            request_id=_request_id(request),
        )
        background_tasks.add_task(
            service.run_full_vector_rebuild_task,
            task_id=task_result.task_id,
            user_id=user_id,
            knowledge_base_id=task_result.knowledge_base_id,
            request_id=_request_id(request),
        )
        return SuccessResponse.create(
            data=_build_full_vector_rebuild_task_response(task_result.task),
            message="Full vector rebuild task started",
            code=status.HTTP_202_ACCEPTED,
        )
    except AppException:
        raise
    except PermissionError as error:
        raise forbidden(str(error), error_code=ErrorCode.SYSTEM_FORBIDDEN, error="KnowledgeAccessDenied") from error
    except FileNotFoundError as error:
        raise not_found(str(error), error_code=ErrorCode.KNOWLEDGE_BASE_NOT_FOUND, error="KnowledgeNotFound") from error
    except Exception as error:
        logger.error("Start full rebuild task failed: %s", error, exc_info=True)
        raise internal_server_error("启动全量向量重建任务失败") from error


@router.get("/rebuild-vectors/full/tasks/{task_id}", response_model=SuccessResponse[FullVectorRebuildTaskResponse])
async def get_full_rebuild_vectors_task(
    task_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    try:
        task = get_knowledge_management_application_service().get_full_vector_rebuild_task(
            task_id=task_id,
            user_id=user_id,
        )
        return SuccessResponse.create(
            data=_build_full_vector_rebuild_task_response(task),
            message="Full vector rebuild task status fetched",
        )
    except AppException:
        raise
    except PermissionError as error:
        raise forbidden(str(error), error_code=ErrorCode.SYSTEM_FORBIDDEN, error="KnowledgeAccessDenied") from error
    except FileNotFoundError as error:
        raise not_found(str(error), error_code=ErrorCode.KNOWLEDGE_BASE_NOT_FOUND, error="KnowledgeNotFound") from error
    except Exception as error:
        logger.error("Get full rebuild task status failed: %s", error, exc_info=True)
        raise internal_server_error("获取全量向量重建任务状态失败") from error


@router.post("/rebuild-vectors/full", response_model=SuccessResponse[FullVectorRebuildResponse])
async def rebuild_vectors_full(
    payload: VectorRebuildRequest,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    try:
        result = get_knowledge_management_application_service().rebuild_all_vectors_for_current_model(
            user_id=user_id,
            knowledge_base_id=payload.knowledge_base_id,
            request_id=_request_id(request),
        )
        return SuccessResponse.create(
            data=_build_full_vector_rebuild_response(result),
            message="Full vector rebuild completed",
        )
    except AppException:
        raise
    except PermissionError as error:
        raise forbidden(str(error), error_code=ErrorCode.SYSTEM_FORBIDDEN, error="KnowledgeAccessDenied") from error
    except FileNotFoundError as error:
        raise not_found(str(error), error_code=ErrorCode.KNOWLEDGE_BASE_NOT_FOUND, error="KnowledgeNotFound") from error
    except Exception as error:
        logger.error("Full rebuild vectors failed: %s", error, exc_info=True)
        raise internal_server_error("全量重建向量失败") from error


@router.post("/search", response_model=SuccessResponse[KnowledgeSearchResponse])
async def search_knowledge(
    payload: SearchRequest,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    try:
        result = await get_knowledge_management_application_service().search_knowledge(
            user_id=user_id,
            query=payload.query,
            top_k=payload.top_k,
            knowledge_base_id=payload.knowledge_base_id,
            retrieval_options={
                "enable_query_rewrite": payload.enable_query_rewrite,
                "enable_exact_phrase": payload.enable_exact_phrase,
                "enable_sparse_keyword": payload.enable_sparse_keyword,
                "enable_dense_vector": payload.enable_dense_vector,
                "enable_fusion_rank": payload.enable_fusion_rank,
                "enable_rerank": payload.enable_rerank,
            },
            request_id=_request_id(request),
        )
        return SuccessResponse.create(data=_build_search_response(result))
    except FileNotFoundError as error:
        raise not_found(str(error), error_code=ErrorCode.KNOWLEDGE_BASE_NOT_FOUND, error="KnowledgeNotFound") from error
    except ValueError as error:
        raise not_found(str(error), error_code=ErrorCode.KNOWLEDGE_BASE_NOT_FOUND, error="KnowledgeNotFound") from error
    except Exception as error:
        logger.error("Search knowledge failed: %s", error, exc_info=True)
        raise internal_server_error("知识检索失败") from error
