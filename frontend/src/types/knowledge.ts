export type {
  Document,
  DocumentUploadResponse,
  KnowledgeBase,
} from '@/adapters/knowledgeAdapter';

export interface UploadDocumentRequest {
  file: File;
  knowledgeBaseId: string;
}
