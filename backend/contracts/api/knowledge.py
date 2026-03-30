from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class DocumentInfo(BaseModel):
    document_id: str = Field(..., description="文档 ID")
    file_name: str = Field(..., description="文件名")
    file_type: str = Field(..., description="文件类型")
    file_size: int = Field(..., description="文件大小（字节）")
    chunk_count: int = Field(..., description="切块数量")
    upload_time: str = Field(..., description="上传时间")
    user_id: str = Field(..., description="所属用户 ID")
    knowledge_base_id: Optional[str] = Field(default=None, description="所属知识库 ID")
    knowledge_base_name: Optional[str] = Field(default=None, description="所属知识库名称")
    status: str = Field(default="completed", description="处理状态")
    processing_stage: Optional[str] = Field(default=None, description="处理阶段")
    processing_progress: Optional[int] = Field(default=None, description="处理进度百分比")
    error_message: Optional[str] = Field(default=None, description="错误信息")
    vectorized_chunk_count: int = Field(default=0, description="已向量化切块数")
    missing_vector_chunk_count: int = Field(default=0, description="待向量化切块数")
    vectorization_status: str = Field(default="unknown", description="向量化状态")
    can_retry_vectorization: bool = Field(default=False, description="是否可重试向量化")
    idempotency_key: Optional[str] = Field(default=None, description="幂等键")


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
    reset_collection: bool = Field(default=False, description="是否重置集合")
    target_dimension: int = Field(default=512, description="目标向量维度")
    error: Optional[str] = Field(default=None, description="错误信息")


class FullVectorRebuildTaskResponse(FullVectorRebuildResponse):
    task_id: str
    status: str = Field(default="pending", description="任务状态")
    scope: str = Field(default="all_knowledge_bases", description="任务作用范围")
    knowledge_base_id: Optional[str] = Field(default=None, description="当前知识库 ID")
    current_document_id: Optional[str] = Field(default=None, description="当前文档 ID")
    current_file_name: Optional[str] = Field(default=None, description="当前文件名")
    created_at: str
    updated_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    idempotency_key: Optional[str] = Field(default=None, description="幂等键")


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
    top_k: int = Field(default=5, ge=1, le=10, description="返回结果数量，最多 10 条")
    knowledge_base_id: Optional[str] = Field(default=None, description="限定搜索的知识库 ID")
    file_type: Optional[str] = Field(default=None, description="限定搜索的文件类型，如 pdf、docx、pptx")
    enable_query_rewrite: bool = Field(default=True, description="是否启用 query rewrite")
    enable_exact_phrase: bool = Field(default=True, description="是否启用 exact phrase 检索")
    enable_sparse_keyword: bool = Field(default=True, description="是否启用 sparse keyword 检索")
    enable_dense_vector: bool = Field(default=True, description="是否启用 dense vector 检索")
    enable_fusion_rank: bool = Field(default=True, description="是否启用 fusion rank")
    enable_rerank: bool = Field(default=True, description="是否启用 rerank")


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="知识库名称")
    description: Optional[str] = Field(default=None, max_length=1000, description="知识库描述")
