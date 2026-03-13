export type {
  Conversation,
  ConversationSummary,
  CreateConversationRequest,
  UpdateConversationRequest,
} from '@/adapters/conversationAdapter';
export type { PaginationMeta } from '@/adapters/common';

export interface PaginatedResponse<T> {
  data: T[];
  pagination: import('@/adapters/common').PaginationMeta;
}
