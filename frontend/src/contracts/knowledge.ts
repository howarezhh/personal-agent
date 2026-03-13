import type { components } from './generated/openapi';

export type KnowledgeBaseCreateRequestContract = components['schemas']['KnowledgeBaseCreateRequest'];
export type KnowledgeBaseContract = components['schemas']['KnowledgeBaseResponse'];
export type KnowledgeBaseListContract = components['schemas']['KnowledgeBaseListResponse'];
export type DocumentContract = components['schemas']['DocumentInfo'];
export type DocumentUploadResponseContract = components['schemas']['DocumentInfo'];
export type DocumentListPayloadContract = components['schemas']['DocumentListResponse'];
export type KnowledgeSearchItemContract = components['schemas']['KnowledgeSearchItem'];
export type KnowledgeSearchResponseContract = components['schemas']['KnowledgeSearchResponse'];
export type SearchRequestContract = components['schemas']['SearchRequest'];

export type KnowledgeBaseEnvelopeContract = components['schemas']['SuccessResponse_KnowledgeBaseResponse_'];
export type KnowledgeBaseListEnvelopeContract = components['schemas']['SuccessResponse_KnowledgeBaseListResponse_'];
export type DocumentInfoEnvelopeContract = components['schemas']['SuccessResponse_DocumentInfo_'];
export type DocumentListEnvelopeContract = components['schemas']['SuccessResponse_DocumentListResponse_'];
export type KnowledgeSearchEnvelopeContract = components['schemas']['SuccessResponse_KnowledgeSearchResponse_'];
