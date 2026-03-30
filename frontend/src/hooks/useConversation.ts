import { useCallback, useState } from 'react';

import { conversationService } from '@/services/conversationService';
import type { Conversation, ConversationSummary, CreateConversationRequest } from '@/types';

const CONVERSATION_PAGE_SIZE = 100;

const sortConversations = (items: ConversationSummary[]): ConversationSummary[] => (
  [...items].sort((left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime())
);

const toConversationSummary = (
  conversation: Conversation,
  previous?: ConversationSummary
): ConversationSummary => ({
  conversationId: conversation.conversationId,
  title: conversation.title,
  messageCount: conversation.messageCount,
  lastMessagePreview: previous?.lastMessagePreview,
  updatedAt: conversation.updatedAt,
});

export const useConversation = () => {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);

  const loadConversations = useCallback(async (page = 1) => {
    try {
      setIsLoading(true);
      setError(null);
      const response = await conversationService.getConversations(page, CONVERSATION_PAGE_SIZE, true);
      setConversations(sortConversations(response.data));
      setCurrentPage(response.pagination.page);
      setTotalPages(response.pagination.totalPages);
    } catch (err: any) {
      setError(err.message || '加载会话列表失败');
    } finally {
      setIsLoading(false);
    }
  }, []);

  const createConversation = useCallback(async (data: CreateConversationRequest) => {
    const conversation = await conversationService.createConversation(data);
    await loadConversations(1);
    return conversation;
  }, [loadConversations]);

  const deleteConversation = useCallback(async (conversationId: string) => {
    await conversationService.deleteConversation(conversationId);
    await loadConversations(currentPage);
  }, [currentPage, loadConversations]);

  const updateConversationTitle = useCallback(async (conversationId: string, title: string) => {
    await conversationService.updateConversation(conversationId, { title });
    await loadConversations(currentPage);
  }, [currentPage, loadConversations]);

  const ensureConversationVisible = useCallback(async (conversationId: string) => {
    const conversation = await conversationService.getConversation(conversationId);
    setConversations((currentConversations) => {
      const previous = currentConversations.find((item) => item.conversationId === conversation.conversationId);
      const nextSummary = toConversationSummary(conversation, previous);
      const nextConversations = currentConversations.filter((item) => item.conversationId !== conversation.conversationId);
      return sortConversations([nextSummary, ...nextConversations]);
    });
    return conversation;
  }, []);

  return {
    conversations,
    isLoading,
    error,
    currentPage,
    totalPages,
    loadConversations,
    createConversation,
    deleteConversation,
    updateConversationTitle,
    ensureConversationVisible,
  };
};

