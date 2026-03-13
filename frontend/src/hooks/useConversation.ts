import { useCallback, useState } from 'react';

import { conversationService } from '@/services/conversationService';
import type { ConversationSummary, CreateConversationRequest } from '@/types';

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
      const response = await conversationService.getConversations(page, 20, true);
      setConversations(response.data);
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
  };
};

