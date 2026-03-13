import type {
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

  async uploadDocument(file: File, knowledgeBaseId: string): Promise<DocumentUploadResponse> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('knowledge_base_id', knowledgeBaseId);

    const response = await api.post<DocumentInfoEnvelopeContract>(API_PATHS.knowledge.upload, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
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
