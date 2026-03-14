import type { AxiosProgressEvent } from 'axios';
import type {
  BatchUploadEnvelopeContract,
  DocumentInfoEnvelopeContract,
  DocumentListEnvelopeContract,
  KnowledgeBaseListEnvelopeContract,
  KnowledgeSearchEnvelopeContract,
  KnowledgeSearchItemContract,
  KnowledgeBaseEnvelopeContract,
} from '@/contracts/knowledge';
import {
  adaptDocument,
  adaptDocumentUploadResponse,
  adaptKnowledgeBase,
} from '@/adapters/knowledgeAdapter';
import type { Document, DocumentUploadResponse, KnowledgeBase } from '@/types';
import { API_PATHS } from '@/constants/api';
import api from './api';

export interface SearchRequest {
  query: string;
  topK?: number;
  knowledgeBaseId?: string;
}

export interface SearchResult {
  id: string;
  content: string;
  score: number;
  source: string;
  metadata?: Record<string, unknown>;
}

export interface SearchResponse {
  query: string;
  knowledgeBaseId?: string;
  results: SearchResult[];
  total: number;
}

export interface DocumentListResponse {
  documents: Document[];
  total: number;
}

export interface KnowledgeBaseListResponse {
  knowledgeBases: KnowledgeBase[];
  total: number;
}

export interface BatchUploadItemResponse {
  fileName: string;
  success: boolean;
  document?: DocumentUploadResponse;
  error?: string;
}

export interface BatchUploadResponse {
  total: number;
  successCount: number;
  failedCount: number;
  results: BatchUploadItemResponse[];
}

export interface VectorRebuildItem {
  documentId: string;
  fileName: string;
  missingBefore: number;
  vectorizedNow: number;
  missingAfter: number;
  success: boolean;
  error?: string;
}

export interface VectorRebuildResponse {
  totalDocuments: number;
  processedDocuments: number;
  succeededDocuments: number;
  failedDocuments: number;
  totalMissingChunksBefore: number;
  totalVectorizedChunksNow: number;
  totalMissingChunksAfter: number;
  details: VectorRebuildItem[];
}

export interface FullVectorRebuildResponse extends VectorRebuildResponse {
  resetCollection: boolean;
  targetDimension: number;
  error?: string;
}

export interface FullVectorRebuildTaskResponse extends FullVectorRebuildResponse {
  taskId: string;
  status: 'pending' | 'running' | 'succeeded' | 'failed';
  scope: string;
  knowledgeBaseId?: string;
  currentDocumentId?: string;
  currentFileName?: string;
  createdAt: string;
  updatedAt?: string;
  startedAt?: string;
  finishedAt?: string;
}

export interface UploadDocumentOptions {
  onProgress?: (percent: number, event: AxiosProgressEvent) => void;
}


const mapVectorRebuildItem = (item: any): VectorRebuildItem => ({
  documentId: item.document_id,
  fileName: item.file_name,
  missingBefore: item.missing_before,
  vectorizedNow: item.vectorized_now,
  missingAfter: item.missing_after,
  success: item.success,
  error: item.error ?? undefined,
});

const mapFullVectorRebuildResponse = (data: any): FullVectorRebuildResponse => ({
  totalDocuments: data.total_documents,
  processedDocuments: data.processed_documents,
  succeededDocuments: data.succeeded_documents,
  failedDocuments: data.failed_documents,
  totalMissingChunksBefore: data.total_missing_chunks_before,
  totalVectorizedChunksNow: data.total_vectorized_chunks_now,
  totalMissingChunksAfter: data.total_missing_chunks_after,
  resetCollection: data.reset_collection,
  targetDimension: data.target_dimension,
  error: data.error ?? undefined,
  details: (data.details ?? []).map(mapVectorRebuildItem),
});

const mapFullVectorRebuildTaskResponse = (data: any): FullVectorRebuildTaskResponse => ({
  ...mapFullVectorRebuildResponse(data),
  taskId: data.task_id,
  status: data.status,
  scope: data.scope,
  knowledgeBaseId: data.knowledge_base_id ?? undefined,
  currentDocumentId: data.current_document_id ?? undefined,
  currentFileName: data.current_file_name ?? undefined,
  createdAt: data.created_at,
  updatedAt: data.updated_at ?? undefined,
  startedAt: data.started_at ?? undefined,
  finishedAt: data.finished_at ?? undefined,
});

export const knowledgeService = {
  async getKnowledgeBases(): Promise<KnowledgeBaseListResponse> {
    const response = await api.get<KnowledgeBaseListEnvelopeContract>(API_PATHS.knowledge.bases);
    return {
      knowledgeBases: response.data.data!.knowledge_bases.map(adaptKnowledgeBase),
      total: response.data.data!.total,
    };
  },

  async createKnowledgeBase(name: string, description?: string): Promise<KnowledgeBase> {
    const response = await api.post<KnowledgeBaseEnvelopeContract>(API_PATHS.knowledge.bases, {
      name,
      description,
    });
    return adaptKnowledgeBase(response.data.data!);
  },

  async deleteKnowledgeBase(knowledgeBaseId: string): Promise<void> {
    await api.delete(`${API_PATHS.knowledge.bases}/${knowledgeBaseId}`);
  },

  async uploadDocument(file: File, knowledgeBaseId: string, options?: UploadDocumentOptions): Promise<DocumentUploadResponse> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('knowledge_base_id', knowledgeBaseId);

    const response = await api.post<DocumentInfoEnvelopeContract>(API_PATHS.knowledge.upload, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (event) => {
        if (!options?.onProgress) {
          return;
        }
        const percent = event.total ? Math.round((event.loaded * 100) / event.total) : 0;
        options.onProgress(percent, event);
      },
    });
    return adaptDocumentUploadResponse(response.data.data!);
  },

  async uploadDocumentsBatch(files: File[], knowledgeBaseId: string): Promise<BatchUploadResponse> {
    const formData = new FormData();
    files.forEach((file) => {
      formData.append('files', file);
    });
    formData.append('knowledge_base_id', knowledgeBaseId);

    const response = await api.post<BatchUploadEnvelopeContract>(API_PATHS.knowledge.uploadBatch, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });

    const data = response.data.data!;
    return {
      total: data.total,
      successCount: data.success_count,
      failedCount: data.failed_count,
      results: data.results.map((item) => ({
        fileName: item.file_name,
        success: item.success,
        document: item.document ? adaptDocumentUploadResponse(item.document) : undefined,
        error: item.error ?? undefined,
      })),
    };
  },

  async getDocumentStatus(documentId: string): Promise<DocumentUploadResponse> {
    const response = await api.get<DocumentInfoEnvelopeContract>(`${API_PATHS.knowledge.documentStatus}/${documentId}/status`);
    return adaptDocumentUploadResponse(response.data.data!);
  },

  async getDocuments(knowledgeBaseId?: string): Promise<DocumentListResponse> {
    const response = await api.get<DocumentListEnvelopeContract>(
      API_PATHS.knowledge.documents,
      { params: knowledgeBaseId ? { knowledge_base_id: knowledgeBaseId } : undefined }
    );
    return {
      documents: response.data.data!.documents.map(adaptDocument),
      total: response.data.data!.total,
    };
  },

  async deleteDocument(documentId: string): Promise<void> {
    await api.delete(`${API_PATHS.knowledge.documents}/${documentId}`);
  },

  async rebuildVectors(knowledgeBaseId?: string): Promise<VectorRebuildResponse> {
    const response = await api.post(API_PATHS.knowledge.rebuildVectors, {
      knowledge_base_id: knowledgeBaseId ?? null,
    });
    const data = response.data.data;
    return {
      totalDocuments: data.total_documents,
      processedDocuments: data.processed_documents,
      succeededDocuments: data.succeeded_documents,
      failedDocuments: data.failed_documents,
      totalMissingChunksBefore: data.total_missing_chunks_before,
      totalVectorizedChunksNow: data.total_vectorized_chunks_now,
      totalMissingChunksAfter: data.total_missing_chunks_after,
      details: (data.details ?? []).map(mapVectorRebuildItem),
    };
  },

  async fullRebuildVectors(knowledgeBaseId?: string): Promise<FullVectorRebuildResponse> {
    const response = await api.post(API_PATHS.knowledge.fullRebuildVectors, {
      knowledge_base_id: knowledgeBaseId ?? null,
    });
    return mapFullVectorRebuildResponse(response.data.data);
  },

  async startFullRebuildVectorsTask(knowledgeBaseId?: string): Promise<FullVectorRebuildTaskResponse> {
    const response = await api.post(API_PATHS.knowledge.fullRebuildVectorTasks, {
      knowledge_base_id: knowledgeBaseId ?? null,
    });
    return mapFullVectorRebuildTaskResponse(response.data.data);
  },

  async getFullRebuildVectorsTask(taskId: string): Promise<FullVectorRebuildTaskResponse> {
    const response = await api.get(`${API_PATHS.knowledge.fullRebuildVectorTasks}/${taskId}`);
    return mapFullVectorRebuildTaskResponse(response.data.data);
  },

  async searchKnowledge(query: string, topK = 5, knowledgeBaseId?: string): Promise<SearchResponse> {
    const response = await api.post<KnowledgeSearchEnvelopeContract>(
      API_PATHS.knowledge.search,
      { query, top_k: topK, knowledge_base_id: knowledgeBaseId }
    );
    return {
      query: response.data.data!.query,
      knowledgeBaseId: response.data.data!.knowledge_base_id ?? undefined,
      results: response.data.data!.results as KnowledgeSearchItemContract[],
      total: response.data.data!.total,
    };
  },
};
