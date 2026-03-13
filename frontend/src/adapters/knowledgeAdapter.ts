import type { DocumentContract, DocumentUploadResponseContract, KnowledgeBaseContract } from '@/contracts/knowledge';

export interface KnowledgeBase {
  knowledgeBaseId: string;
  userId: string;
  name: string;
  description?: string | null;
  isDefault: boolean;
  isActive: boolean;
  createdAt?: string;
  updatedAt?: string;
}

export interface Document {
  documentId: string;
  userId: string;
  knowledgeBaseId?: string;
  knowledgeBaseName?: string;
  filename?: string;
  fileName?: string;
  fileType: string;
  fileSize: number;
  filePath?: string;
  status?: 'pending' | 'processing' | 'completed' | 'failed';
  chunkCount: number;
  uploadTime?: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface DocumentUploadResponse {
  documentId: string;
  knowledgeBaseId?: string;
  knowledgeBaseName?: string;
  filename?: string;
  fileName?: string;
  fileType?: string;
  fileSize?: number;
  chunkCount?: number;
  uploadTime?: string;
  status?: string;
}

const normalizeDocumentStatus = (status: string): Document['status'] => {
  if (status === 'pending' || status === 'processing' || status === 'completed' || status === 'failed') {
    return status;
  }

  return undefined;
};

export const adaptKnowledgeBase = (kb: KnowledgeBaseContract): KnowledgeBase => ({
  knowledgeBaseId: kb.knowledge_base_id,
  userId: kb.user_id,
  name: kb.name,
  description: kb.description,
  isDefault: kb.is_default,
  isActive: kb.is_active,
  createdAt: kb.created_at ?? undefined,
  updatedAt: kb.updated_at ?? undefined,
});

export const adaptDocument = (doc: DocumentContract): Document => ({
  documentId: doc.document_id,
  userId: doc.user_id,
  knowledgeBaseId: doc.knowledge_base_id ?? undefined,
  knowledgeBaseName: doc.knowledge_base_name ?? undefined,
  filename: doc.file_name,
  fileName: doc.file_name,
  fileType: doc.file_type,
  fileSize: doc.file_size,
  filePath: undefined,
  status: normalizeDocumentStatus(doc.status),
  chunkCount: doc.chunk_count,
  uploadTime: doc.upload_time ?? undefined,
  createdAt: doc.upload_time ?? undefined,
  updatedAt: doc.upload_time ?? undefined,
});

export const adaptDocumentUploadResponse = (doc: DocumentUploadResponseContract): DocumentUploadResponse => ({
  documentId: doc.document_id,
  knowledgeBaseId: doc.knowledge_base_id ?? undefined,
  knowledgeBaseName: doc.knowledge_base_name ?? undefined,
  filename: doc.file_name,
  fileName: doc.file_name,
  fileType: doc.file_type,
  fileSize: doc.file_size,
  chunkCount: doc.chunk_count,
  uploadTime: doc.upload_time ?? undefined,
  status: doc.status,
});
