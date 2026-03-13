import { create } from 'zustand';

import type { Document, KnowledgeBase } from '@/types';

interface KnowledgeState {
  knowledgeBases: KnowledgeBase[];
  selectedKnowledgeBaseId: string | null;
  documents: Document[];
  isLoading: boolean;
  error: string | null;
  setKnowledgeBases: (knowledgeBases: KnowledgeBase[]) => void;
  setSelectedKnowledgeBaseId: (knowledgeBaseId: string | null) => void;
  setDocuments: (documents: Document[]) => void;
  addDocument: (document: Document) => void;
  removeDocument: (documentId: string) => void;
  updateDocument: (documentId: string, updates: Partial<Document>) => void;
  setLoading: (isLoading: boolean) => void;
  setError: (error: string | null) => void;
}

export const useKnowledgeStore = create<KnowledgeState>((set) => ({
  knowledgeBases: [],
  selectedKnowledgeBaseId: null,
  documents: [],
  isLoading: false,
  error: null,
  setKnowledgeBases: (knowledgeBases) => set({ knowledgeBases }),
  setSelectedKnowledgeBaseId: (selectedKnowledgeBaseId) => set({ selectedKnowledgeBaseId }),
  setDocuments: (documents) => set({ documents }),
  addDocument: (document) => set((state) => ({ documents: [...state.documents, document] })),
  removeDocument: (documentId) => set((state) => ({ documents: state.documents.filter((doc) => doc.documentId !== documentId) })),
  updateDocument: (documentId, updates) =>
    set((state) => ({ documents: state.documents.map((doc) => (doc.documentId === documentId ? { ...doc, ...updates } : doc)) })),
  setLoading: (isLoading) => set({ isLoading }),
  setError: (error) => set({ error }),
}));

