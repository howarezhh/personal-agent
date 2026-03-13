"""Knowledge-base API routes."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field

from backend.api.dependencies import get_current_user_id
from backend.api.models import MessageResponse, SuccessResponse
from backend.application.service_factory import (
    build_document_application_service,
    build_knowledge_application_service,
)
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


def get_document_application_service() -> DocumentApplicationService:
    return build_document_application_service()


def get_knowledge_application_service() -> KnowledgeBaseApplicationService:
    return build_knowledge_application_service()


def _request_id(request: Request) -> str | None:
    return getattr(getattr(request, "state", None), "request_id", None)


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

        document = await get_document_application_service().upload_document(
            user_id=user_id,
            upload_file=file,
            knowledge_base_id=target_knowledge_base.knowledge_base_id,
            request_id=_request_id(request),
        )
        return SuccessResponse.create(data=DocumentInfo(**document), message="Document uploaded successfully")
    except HTTPException:
        raise
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    except Exception as error:
        logger.error("Upload document failed: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"上传知识库文档失败: {error}")


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
