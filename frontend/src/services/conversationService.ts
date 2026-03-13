import type {
  ConversationEnvelopeContract,
  PaginatedConversationMessageResponseContract,
  PaginatedConversationSummaryResponseContract,
} from '@/contracts/conversation';
import { adaptPagination } from '@/adapters/common';
import { adaptMessage } from '@/adapters/chatAdapter';
import {
  adaptConversation,
  adaptConversationSummary,
} from '@/adapters/conversationAdapter';
import type {
  Conversation,
  ConversationSummary,
  CreateConversationRequest,
  Message,
  PaginationMeta,
  UpdateConversationRequest,
} from '@/types';
import { API_PATHS } from '@/constants/api';
import api from './api';

export interface PaginatedResult<T> {
  data: T[];
  pagination: PaginationMeta;
}

export const conversationService = {
  async getConversations(page = 1, pageSize = 20, onlyActive = true): Promise<PaginatedResult<ConversationSummary>> {
    const response = await api.get<PaginatedConversationSummaryResponseContract>(API_PATHS.conversations, {
      params: { page, page_size: pageSize, only_active: onlyActive },
    });
    const conversationItems = response.data.data ?? [];

    return {
      data: conversationItems.map(adaptConversationSummary),
      pagination: adaptPagination(response.data.pagination),
    };
  },

  async getConversation(conversationId: string): Promise<Conversation> {
    const response = await api.get<ConversationEnvelopeContract>(`${API_PATHS.conversations}/${conversationId}`);
    return adaptConversation(response.data.data!);
  },

  async getConversationMessages(conversationId: string, page = 1, pageSize = 100): Promise<PaginatedResult<Message>> {
    const response = await api.get<PaginatedConversationMessageResponseContract>(
      `${API_PATHS.conversations}/${conversationId}/messages`,
      { params: { page, page_size: pageSize } }
    );
    const messageItems = response.data.data ?? [];

    return {
      data: messageItems.map(adaptMessage),
      pagination: adaptPagination(response.data.pagination),
    };
  },

  async createConversation(data: CreateConversationRequest): Promise<Conversation> {
    const response = await api.post<ConversationEnvelopeContract>(API_PATHS.conversations, data);
    return adaptConversation(response.data.data!);
  },

  async updateConversation(conversationId: string, data: UpdateConversationRequest): Promise<Conversation> {
    const response = await api.put<ConversationEnvelopeContract>(
      `${API_PATHS.conversations}/${conversationId}`,
      data
    );
    return adaptConversation(response.data.data!);
  },

  async deleteConversation(conversationId: string): Promise<void> {
    await api.delete(`${API_PATHS.conversations}/${conversationId}`);
  },
};
