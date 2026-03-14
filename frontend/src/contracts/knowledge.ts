import type { components } from './generated/openapi';

export type KnowledgeBaseCreateRequestContract = components['schemas']['KnowledgeBaseCreateRequest'];
export type KnowledgeBaseContract = components['schemas']['KnowledgeBaseResponse'];
export type KnowledgeBaseListContract = components['schemas']['KnowledgeBaseListResponse'];
export type DocumentContract = components['schemas']['DocumentInfo'];
export type DocumentUploadResponseContract = components['schemas']['DocumentInfo'];
export type DocumentListPayloadContract = components['schemas']['DocumentListResponse'];
export type BatchUploadItemResponseContract = components['schemas']['BatchUploadItemResponse'];
export type BatchUploadResponseContract = components['schemas']['BatchUploadResponse'];
export type KnowledgeSearchItemContract = components['schemas']['KnowledgeSearchItem'];
export type KnowledgeSearchResponseContract = components['schemas']['KnowledgeSearchResponse'];
export type SearchRequestContract = components['schemas']['SearchRequest'];

export type VectorRebuildRequestContract = components['schemas']['VectorRebuildRequest'];
export type VectorRebuildResponseContract = components['schemas']['VectorRebuildResponse'];
export type FullVectorRebuildResponseContract = components['schemas']['FullVectorRebuildResponse'];
export type FullVectorRebuildTaskResponseContract = components['schemas']['FullVectorRebuildTaskResponse'];

export type KnowledgeBaseEnvelopeContract = components['schemas']['SuccessResponse_KnowledgeBaseResponse_'];
export type KnowledgeBaseListEnvelopeContract = components['schemas']['SuccessResponse_KnowledgeBaseListResponse_'];
export type DocumentInfoEnvelopeContract = components['schemas']['SuccessResponse_DocumentInfo_'];
export type DocumentListEnvelopeContract = components['schemas']['SuccessResponse_DocumentListResponse_'];
export type BatchUploadEnvelopeContract = components['schemas']['SuccessResponse_BatchUploadResponse_'];
export type KnowledgeSearchEnvelopeContract = components['schemas']['SuccessResponse_KnowledgeSearchResponse_'];
export type VectorRebuildEnvelopeContract = components['schemas']['SuccessResponse_VectorRebuildResponse_'];
export type FullVectorRebuildEnvelopeContract = components['schemas']['SuccessResponse_FullVectorRebuildResponse_'];
export type FullVectorRebuildTaskEnvelopeContract = components['schemas']['SuccessResponse_FullVectorRebuildTaskResponse_'];
