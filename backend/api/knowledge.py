"""Knowledge-base API routes."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field

from backend.api.dependencies import get_current_user_id
from backend.api.models import MessageResponse, SuccessResponse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.application.services import DocumentApplicationService, KnowledgeBaseApplicationService
from backend.utils.logger import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


class DocumentInfo(BaseModel):
    document_id: str = Field(..., description="文档 ID")
    file_name: str = Field(..., description="文件名")
    file_type: str = Field(..., description="文件类型")
    file_size: int = Field(..., description="文件大小（字节）")
    chunk_count: int = Field(..., description="文本分块数")
    upload_time: str = Field(..., description="上传时间")
    user_id: str = Field(..., description="所属用户 ID")
    knowledge_base_id: Optional[str] = Field(default=None, description="所属知识库 ID")
    knowledge_base_name: Optional[str] = Field(default=None, description="所属知识库名称")
    status: str = Field(default="completed", description="处理状态")
    processing_stage: Optional[str] = Field(default=None, description="处理阶段")
    processing_progress: Optional[int] = Field(default=None, description="处理进度百分比")
    error_message: Optional[str] = Field(default=None, description="错误信息")
    vectorized_chunk_count: int = Field(default=0, description="已向量化分块数")
    missing_vector_chunk_count: int = Field(default=0, description="待向量化分块数")
    vectorization_status: str = Field(default="unknown", description="向量化状态")
    can_retry_vectorization: bool = Field(default=False, description="是否可重试向量化")


class VectorRebuildRequest(BaseModel):
    knowledge_base_id: Optional[str] = Field(default=None, description="限定重建的知识库 ID")


class VectorRebuildItem(BaseModel):
    document_id: str
    file_name: str
    missing_before: int
    vectorized_now: int
    missing_after: int
    success: bool
    error: Optional[str] = None


class VectorRebuildResponse(BaseModel):
    total_documents: int
    processed_documents: int
    succeeded_documents: int
    failed_documents: int
    total_missing_chunks_before: int
    total_vectorized_chunks_now: int
    total_missing_chunks_after: int
    details: list[VectorRebuildItem]


class FullVectorRebuildResponse(VectorRebuildResponse):
    reset_collection: bool = Field(default=False, description="???????????")
    target_dimension: int = Field(default=512, description="??????????")
    error: Optional[str] = Field(default=None, description="??????????")


class FullVectorRebuildTaskResponse(FullVectorRebuildResponse):
    task_id: str
    status: str = Field(default="pending", description="?????pending/running/succeeded/failed")
    scope: str = Field(default="all_knowledge_bases", description="????")
    knowledge_base_id: Optional[str] = Field(default=None, description="???????? ID")
    current_document_id: Optional[str] = Field(default=None, description="???????? ID")
    current_file_name: Optional[str] = Field(default=None, description="?????????")
    created_at: str
    updated_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class BatchUploadItemResponse(BaseModel):
    file_name: str
    success: bool
    document: Optional[DocumentInfo] = None
    error: Optional[str] = None


class BatchUploadResponse(BaseModel):
    total: int
    success_count: int
    failed_count: int
    results: list[BatchUploadItemResponse]


class KnowledgeBaseResponse(BaseModel):
    knowledge_base_id: str
    user_id: str
    name: str
    description: Optional[str] = None
    is_default: bool
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class KnowledgeBaseListResponse(BaseModel):
    knowledge_bases: list[KnowledgeBaseResponse]
    total: int


class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo]
    total: int


class KnowledgeSearchItem(BaseModel):
    id: str
    content: str
    score: float
    source: str
    metadata: dict[str, Any]


class KnowledgeSearchResponse(BaseModel):
    query: str
    knowledge_base_id: Optional[str] = None
    results: list[KnowledgeSearchItem]
    total: int


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="搜索词")
    top_k: int = Field(default=5, ge=1, le=20, description="返回结果数量")
    knowledge_base_id: Optional[str] = Field(default=None, description="限定搜索的知识库 ID")


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="知识库名称")
    description: Optional[str] = Field(default=None, max_length=1000, description="知识库描述")


def get_document_application_service() -> "DocumentApplicationService":
    from backend.application.service_factory import build_document_application_service

    return build_document_application_service()


def get_knowledge_application_service() -> "KnowledgeBaseApplicationService":
    from backend.application.service_factory import build_knowledge_application_service

    return build_knowledge_application_service()


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


def _build_full_vector_rebuild_response(result: dict[str, Any]) -> FullVectorRebuildResponse:
    return FullVectorRebuildResponse(
        total_documents=result["total_documents"],
        processed_documents=result["processed_documents"],
        succeeded_documents=result["succeeded_documents"],
        failed_documents=result["failed_documents"],
        total_missing_chunks_before=result["total_missing_chunks_before"],
        total_vectorized_chunks_now=result["total_vectorized_chunks_now"],
        total_missing_chunks_after=result["total_missing_chunks_after"],
        details=_build_vector_rebuild_items(result.get("details", [])),
        reset_collection=result.get("reset_collection", False),
        target_dimension=result.get("target_dimension", 512),
        error=result.get("error"),
    )


def _build_full_vector_rebuild_task_response(task: dict[str, Any]) -> FullVectorRebuildTaskResponse:
    return FullVectorRebuildTaskResponse(
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
        total_documents=task.get("total_documents", 0),
        processed_documents=task.get("processed_documents", 0),
        succeeded_documents=task.get("succeeded_documents", 0),
        failed_documents=task.get("failed_documents", 0),
        total_missing_chunks_before=task.get("total_missing_chunks_before", 0),
        total_vectorized_chunks_now=task.get("total_vectorized_chunks_now", 0),
        total_missing_chunks_after=task.get("total_missing_chunks_after", 0),
        details=_build_vector_rebuild_items(task.get("details", [])),
        reset_collection=task.get("reset_collection", False),
        target_dimension=task.get("target_dimension", 512),
        error=task.get("error"),
    )


@router.get("/bases", response_model=SuccessResponse[KnowledgeBaseListResponse])
async def get_knowledge_bases(user_id: str = Depends(get_current_user_id)):
    knowledge_bases, total = get_knowledge_application_service().list_knowledge_bases(user_id=user_id)
    return SuccessResponse.create(
        data=KnowledgeBaseListResponse(
            knowledge_bases=[KnowledgeBaseResponse(**item.to_dict()) for item in knowledge_bases],
            total=total,
        )
    )


@router.post("/bases", response_model=SuccessResponse[KnowledgeBaseResponse], status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(request: KnowledgeBaseCreateRequest, user_id: str = Depends(get_current_user_id)):
    try:
        knowledge_base = get_knowledge_application_service().create_knowledge_base(
            user_id=user_id,
            name=request.name,
            description=request.description,
        )
        return SuccessResponse.create(
            data=KnowledgeBaseResponse(**knowledge_base.to_dict()),
            message="Knowledge base created successfully",
            code=status.HTTP_201_CREATED,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    except Exception as error:
        logger.error("Create knowledge base failed: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="创建知识库失败")


@router.delete("/bases/{knowledge_base_id}", response_model=MessageResponse)
async def delete_knowledge_base(
    knowledge_base_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    try:
        knowledge_base = get_knowledge_application_service().delete_knowledge_base(
            knowledge_base_id=knowledge_base_id,
            user_id=user_id,
            request_id=_request_id(request),
        )
        return MessageResponse.create(message=f"Knowledge base '{knowledge_base.name}' deleted successfully")
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error))
    except Exception as error:
        logger.error("Delete knowledge base failed: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除知识库失败")


@router.post("/upload", response_model=SuccessResponse[DocumentInfo])
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="待上传的知识库文档"),
    knowledge_base_id: Optional[str] = Form(default=None, description="所属知识库 ID"),
    user_id: str = Depends(get_current_user_id),
):
    try:
        knowledge_service = get_knowledge_application_service()
        target_knowledge_base = (
            knowledge_service.get_user_knowledge_base(user_id=user_id, knowledge_base_id=knowledge_base_id)
            if knowledge_base_id
            else knowledge_service.ensure_default_for_user(user_id=user_id)
        )
        if not target_knowledge_base:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在或无权访问")

        document_service = get_document_application_service()
        file_record = await document_service.create_document_upload(
            user_id=user_id,
            upload_file=file,
            knowledge_base_id=target_knowledge_base.knowledge_base_id,
            request_id=_request_id(request),
        )
        background_tasks.add_task(document_service.process_uploaded_document, file_record.file_id, _request_id(request))
        document = document_service.get_document_status(document_id=file_record.file_id, user_id=user_id)
        return SuccessResponse.create(data=DocumentInfo(**document), message="Document upload accepted")
    except HTTPException:
        raise
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    except Exception as error:
        logger.error("Upload document failed: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"上传知识库文档失败: {error}")


@router.post("/upload/batch", response_model=SuccessResponse[BatchUploadResponse])
async def upload_documents_batch(
    request: Request,
    files: list[UploadFile] = File(..., description="待上传的知识库文档列表"),
    knowledge_base_id: Optional[str] = Form(default=None, description="所属知识库 ID"),
    user_id: str = Depends(get_current_user_id),
):
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="至少需要上传一个文件")

    try:
        knowledge_service = get_knowledge_application_service()
        target_knowledge_base = (
            knowledge_service.get_user_knowledge_base(user_id=user_id, knowledge_base_id=knowledge_base_id)
            if knowledge_base_id
            else knowledge_service.ensure_default_for_user(user_id=user_id)
        )
        if not target_knowledge_base:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在或无权访问")

        result = await get_document_application_service().upload_documents_batch(
            user_id=user_id,
            upload_files=files,
            knowledge_base_id=target_knowledge_base.knowledge_base_id,
            request_id=_request_id(request),
        )
        return SuccessResponse.create(
            data=BatchUploadResponse(
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
            ),
            message="Batch document upload completed",
        )
    except HTTPException:
        raise
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    except Exception as error:
        logger.error("Batch upload document failed: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"批量上传知识库文档失败: {error}")


@router.get("/documents/{document_id}/status", response_model=SuccessResponse[DocumentInfo])
async def get_document_status(
    document_id: str,
    user_id: str = Depends(get_current_user_id),
):
    try:
        document = get_document_application_service().get_document_status(document_id=document_id, user_id=user_id)
        return SuccessResponse.create(data=DocumentInfo(**document))
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error))
    except Exception as error:
        logger.error("Get document status failed: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取知识库文档状态失败")


@router.get("/documents", response_model=SuccessResponse[DocumentListResponse])
async def get_documents(
    knowledge_base_id: Optional[str] = Query(default=None, description="按知识库过滤文档"),
    user_id: str = Depends(get_current_user_id),
):
    try:
        documents = get_document_application_service().list_documents(user_id=user_id, knowledge_base_id=knowledge_base_id)
        return SuccessResponse.create(
            data=DocumentListResponse(documents=[DocumentInfo(**document) for document in documents], total=len(documents))
        )
    except Exception as error:
        logger.error("Get knowledge documents failed: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取知识库文档列表失败")


@router.delete("/documents/{document_id}", response_model=MessageResponse)
async def delete_document(
    document_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    try:
        cleanup_result = get_document_application_service().delete_document(
            document_id=document_id,
            user_id=user_id,
            request_id=_request_id(request),
        )
        return MessageResponse.create(
            message=f"Document deleted successfully ({cleanup_result['chunk_count']} chunks removed)",
            code=200,
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error))
    except Exception as error:
        logger.error("Delete document failed: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除知识库文档失败")


@router.post("/rebuild-vectors", response_model=SuccessResponse[VectorRebuildResponse])
async def rebuild_vectors(
    payload: VectorRebuildRequest,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    try:
        logger.info(
            "Received rebuild vectors request: request_id=%s user_id=%s knowledge_base_id=%s",
            _request_id(request),
            user_id,
            payload.knowledge_base_id,
        )
        if payload.knowledge_base_id:
            knowledge_base = get_knowledge_application_service().get_user_knowledge_base(
                user_id=user_id,
                knowledge_base_id=payload.knowledge_base_id,
            )
            if not knowledge_base:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在或无权访问")

        result = get_document_application_service().retry_pending_vectorizations(
            user_id=user_id,
            knowledge_base_id=payload.knowledge_base_id,
            request_id=_request_id(request),
        )
        logger.info(
            "Rebuild vectors request completed: request_id=%s user_id=%s knowledge_base_id=%s succeeded=%s failed=%s missing_before=%s missing_after=%s",
            _request_id(request),
            user_id,
            payload.knowledge_base_id,
            result["succeeded_documents"],
            result["failed_documents"],
            result["total_missing_chunks_before"],
            result["total_missing_chunks_after"],
        )
        return SuccessResponse.create(
            data=VectorRebuildResponse(
                total_documents=result["total_documents"],
                processed_documents=result["processed_documents"],
                succeeded_documents=result["succeeded_documents"],
                failed_documents=result["failed_documents"],
                total_missing_chunks_before=result["total_missing_chunks_before"],
                total_vectorized_chunks_now=result["total_vectorized_chunks_now"],
                total_missing_chunks_after=result["total_missing_chunks_after"],
                details=[
                    VectorRebuildItem(
                        document_id=item["document_id"],
                        file_name=item["file_name"],
                        missing_before=item["missing_before"],
                        vectorized_now=item["vectorized_now"],
                        missing_after=item["missing_after"],
                        success=item["success"],
                        error=item.get("error"),
                    )
                    for item in result["details"]
                ],
            ),
            message="Vector rebuild completed",
        )
    except HTTPException:
        raise
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except Exception as error:
        logger.error("Rebuild vectors failed: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="重建向量失败") from error


@router.post("/rebuild-vectors/full/tasks", response_model=SuccessResponse[FullVectorRebuildTaskResponse], status_code=status.HTTP_202_ACCEPTED)
async def start_full_rebuild_vectors_task(
    payload: VectorRebuildRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    try:
        request_id = _request_id(request)
        logger.warning(
            "Received full rebuild task start request: request_id=%s user_id=%s knowledge_base_id=%s",
            request_id,
            user_id,
            payload.knowledge_base_id,
        )
        document_service = get_document_application_service()
        task = document_service.start_full_vector_rebuild_task(
            user_id=user_id,
            knowledge_base_id=None,
            request_id=request_id,
        )
        background_tasks.add_task(
            document_service.run_full_vector_rebuild_task,
            task_id=task["task_id"],
            user_id=user_id,
            knowledge_base_id=None,
            request_id=request_id,
        )
        logger.warning(
            "Full rebuild task scheduled: request_id=%s user_id=%s task_id=%s",
            request_id,
            user_id,
            task["task_id"],
        )
        return SuccessResponse.create(
            data=_build_full_vector_rebuild_task_response(task),
            message="Full vector rebuild task started",
            code=status.HTTP_202_ACCEPTED,
        )
    except HTTPException:
        raise
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except Exception as error:
        logger.error("Start full rebuild task failed: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="????????????") from error


@router.get("/rebuild-vectors/full/tasks/{task_id}", response_model=SuccessResponse[FullVectorRebuildTaskResponse])
async def get_full_rebuild_vectors_task(
    task_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    try:
        logger.info(
            "Received full rebuild task status request: request_id=%s user_id=%s task_id=%s",
            _request_id(request),
            user_id,
            task_id,
        )
        task = get_document_application_service().get_full_vector_rebuild_task(task_id=task_id, user_id=user_id)
        return SuccessResponse.create(
            data=_build_full_vector_rebuild_task_response(task),
            message="Full vector rebuild task status fetched",
        )
    except HTTPException:
        raise
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except Exception as error:
        logger.error("Get full rebuild task status failed: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="??????????????") from error


@router.post("/rebuild-vectors/full", response_model=SuccessResponse[FullVectorRebuildResponse])
async def rebuild_vectors_full(
    payload: VectorRebuildRequest,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    try:
        logger.warning(
            "Received full rebuild vectors request: request_id=%s user_id=%s knowledge_base_id=%s",
            _request_id(request),
            user_id,
            payload.knowledge_base_id,
        )
        result = get_document_application_service().rebuild_all_vectors_for_current_model(
            user_id=user_id,
            knowledge_base_id=None,
            request_id=_request_id(request),
        )
        logger.warning(
            "Full rebuild vectors request completed: request_id=%s user_id=%s knowledge_base_id=%s succeeded=%s failed=%s vectorized_now=%s remaining=%s target_dimension=%s",
            _request_id(request),
            user_id,
            payload.knowledge_base_id,
            result["succeeded_documents"],
            result["failed_documents"],
            result["total_vectorized_chunks_now"],
            result["total_missing_chunks_after"],
            result["target_dimension"],
        )
        return SuccessResponse.create(
            data=_build_full_vector_rebuild_response(result),
            message="Full vector rebuild completed",
        )
    except HTTPException:
        raise
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except Exception as error:
        logger.error("Full rebuild vectors failed: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="????????") from error


@router.post("/search", response_model=SuccessResponse[KnowledgeSearchResponse])
async def search_knowledge(
    payload: SearchRequest,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    try:
        results = get_knowledge_application_service().search_knowledge(
            user_id=user_id,
            query=payload.query,
            top_k=payload.top_k,
            knowledge_base_id=payload.knowledge_base_id,
            request_id=_request_id(request),
        )
        return SuccessResponse.create(
            data=KnowledgeSearchResponse(
                query=payload.query,
                knowledge_base_id=payload.knowledge_base_id,
                results=[KnowledgeSearchItem(**item) for item in results],
                total=len(results),
            )
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except Exception as error:
        logger.error("Search knowledge failed: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="搜索知识库失败")
