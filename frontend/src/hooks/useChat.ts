import { useCallback, useRef, useState } from 'react';

import { API_PATHS } from '@/constants/api';
import {
  adaptDoneEventContent,
  adaptStreamEventMetadata,
  toAskRequestContract,
  type AskRequest,
  type Message,
} from '@/types';
import { chatService } from '@/services/chatService';
import { conversationService } from '@/services/conversationService';
import { useChatStore } from '@/stores/chatStore';

import { useSSE } from './useSSE';

export const useChat = () => {
  const {
    messages,
    currentConversationId,
    isStreaming,
    streamingContent,
    thinkingSteps,
    citations,
    error,
    knowledgeBaseEnabled,
    selectedKnowledgeBaseId,
    setMessages,
    addMessage,
    setCurrentConversationId,
    setStreaming,
    setStreamingContent,
    appendStreamingContent,
    addThinkingStep,
    clearThinkingSteps,
    setCitations,
    setError,
    setKnowledgeBaseEnabled,
    setSelectedKnowledgeBaseId,
    reset,
  } = useChatStore();

  const { connect, cancel } = useSSE();
  const [isLoading, setIsLoading] = useState(false);
  const streamIdRef = useRef<string | null>(null);

  const isStreamBootstrapEvent = (value: unknown) => String(value || '').trim() === 'stream_started';

  const refreshMessages = useCallback(
    async (conversationId: string) => {
      const response = await conversationService.getConversationMessages(conversationId);
      setMessages(response.data);
      setCurrentConversationId(conversationId);
    },
    [setCurrentConversationId, setMessages]
  );

  const loadMessages = useCallback(
    async (conversationId: string) => {
      try {
        setIsLoading(true);
        if (isStreaming) {
          cancel();
          setStreaming(false);
          streamIdRef.current = null;
        }
        clearThinkingSteps();
        setCitations([]);
        setStreamingContent('');
        const response = await conversationService.getConversationMessages(conversationId);
        setCurrentConversationId(conversationId);
        setMessages(response.data);
      } catch (err: any) {
        setError(err.message || '加载消息失败');
      } finally {
        setIsLoading(false);
      }
    },
    [cancel, clearThinkingSteps, isStreaming, setCitations, setCurrentConversationId, setError, setMessages, setStreaming, setStreamingContent]
  );

  const sendMessage = useCallback(
    async (question: string, conversationId?: string) => {
      const targetConversationId = conversationId || currentConversationId;
      setError(null);
      clearThinkingSteps();
      setStreamingContent('');
      setStreaming(true);
      streamIdRef.current = null;

      const userMessage: Message = {
        messageId: `temp-${Date.now()}`,
        conversationId: targetConversationId || '',
        messageType: 'user',
        content: question,
        sequenceNumber: messages.length + 1,
        createdAt: new Date().toISOString(),
      };
      addMessage(userMessage);

      const request: AskRequest = {
        question,
        conversationId: targetConversationId || undefined,
        stream: true,
        enableKnowledgeBase: knowledgeBaseEnabled,
        knowledgeBaseId: selectedKnowledgeBaseId || undefined,
      };

      await connect(
        API_PATHS.chat.ask,
        toAskRequestContract(request),
        (event) => {
          const streamMetadata = adaptStreamEventMetadata(event.metadata);
          const streamId = typeof streamMetadata.streamId === 'string'
            ? streamMetadata.streamId
            : undefined;
          if (streamId) {
            streamIdRef.current = streamId;
          }

          switch (event.type) {
            case 'thinking': {
              const thinkingText = event.message || event.content || 'thinking';
              if (!isStreamBootstrapEvent(thinkingText)) {
                addThinkingStep({
                  step: String(thinkingText),
                  description: String(thinkingText),
                  timestamp: event.timestamp,
                });
              }
              break;
            }
            case 'content':
              appendStreamingContent(String(event.content || ''));
              break;
            case 'tool_call':
              addThinkingStep({
                step: '工具调用',
                description: String(event.message || JSON.stringify(event.content || event.metadata || {})),
                timestamp: event.timestamp,
              });
              break;
            case 'result': {
              const resultPayload = adaptDoneEventContent(event.content);
              if (resultPayload.citations) {
                setCitations(resultPayload.citations);
              }
              break;
            }
            case 'error':
              setError(String(event.message || event.content || 'Message send failed'));
              setStreaming(false);
              break;
            case 'done': {
              const doneData = adaptDoneEventContent(event.content);
              const doneConversationId = doneData.conversationId ?? event.conversationId;
              if (typeof doneConversationId === 'string' && doneConversationId.length > 0) {
                setCurrentConversationId(doneConversationId);
                void refreshMessages(doneConversationId).finally(() => {
                  setStreamingContent('');
                });
              } else {
                setStreamingContent('');
              }
              if (doneData.citations) {
                setCitations(doneData.citations);
              }
              setStreaming(false);
              break;
            }
          }
        },
        (streamError) => {
          setError(streamError.message);
          setStreaming(false);
        },
        () => setStreaming(false)
      );
    },
    [
      addMessage,
      addThinkingStep,
      appendStreamingContent,
      clearThinkingSteps,
      connect,
      currentConversationId,
      knowledgeBaseEnabled,
      messages.length,
      refreshMessages,
      selectedKnowledgeBaseId,
      setCitations,
      setCurrentConversationId,
      setError,
      setStreaming,
      setStreamingContent,
    ]
  );

  const stopStreaming = useCallback(async () => {
    cancel();
    if (streamIdRef.current) {
      await chatService.pauseStream(streamIdRef.current);
    }
    setStreaming(false);
  }, [cancel, setStreaming]);

  return {
    messages,
    currentConversationId,
    isStreaming,
    streamingContent,
    thinkingSteps,
    citations,
    error,
    isLoading,
    knowledgeBaseEnabled,
    selectedKnowledgeBaseId,
    loadMessages,
    sendMessage,
    stopStreaming,
    setKnowledgeBaseEnabled,
    setSelectedKnowledgeBaseId,
    reset,
  };
};
