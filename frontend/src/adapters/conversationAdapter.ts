import type { ConversationContract, ConversationSummaryContract } from '@/contracts/conversation';

export interface Conversation {
  conversationId: string;
  userId: string;
  title: string;
  description?: string;
  messageCount: number;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface ConversationSummary {
  conversationId: string;
  title: string;
  messageCount: number;
  lastMessagePreview?: string;
  updatedAt: string;
}

export interface CreateConversationRequest {
  title?: string;
  description?: string;
}

export interface UpdateConversationRequest {
  title?: string;
  description?: string;
}

export const adaptConversation = (conversation: ConversationContract): Conversation => ({
  conversationId: conversation.conversation_id,
  userId: conversation.user_id,
  title: conversation.title,
  description: conversation.description ?? undefined,
  messageCount: conversation.message_count,
  isActive: conversation.is_active,
  createdAt: conversation.created_at,
  updatedAt: conversation.updated_at,
});

export const adaptConversationSummary = (conversation: ConversationSummaryContract): ConversationSummary => ({
  conversationId: conversation.conversation_id,
  title: conversation.title,
  messageCount: conversation.message_count,
  lastMessagePreview: conversation.last_message_preview ?? undefined,
  updatedAt: conversation.updated_at,
});
