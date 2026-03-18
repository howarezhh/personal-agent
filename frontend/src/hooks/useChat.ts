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

const extractResultText = (payload: { finalContent?: string }): string | undefined => {
  if (typeof payload.finalContent === 'string' && payload.finalContent.trim()) {
    return payload.finalContent;
  }
  return undefined;
};

const stringifyPayload = (value: unknown): string => {
  if (typeof value === 'string') {
    return value;
  }

  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

const resolveThinkingText = (
  message: unknown,
  content: unknown,
  payload: Record<string, unknown>
): string => {
  const candidates = [
    message,
    typeof content === 'string' ? content : undefined,
    payload.message,
    payload.description,
    payload.event,
  ];

  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim()) {
      return candidate;
    }
  }

  return 'thinking';
};

const resolveToolStepTitle = (toolName?: string, status?: string): string => {
  const prefix = status === 'starting'
    ? 'Tool start'
    : status === 'completed'
      ? 'Tool done'
      : status === 'failed'
        ? 'Tool failed'
        : 'Tool call';

  return toolName ? `${prefix} - ${toolName}` : prefix;
};

const buildToolDescription = (
  payload: Record<string, unknown>,
  status?: string,
  fallbackValue?: unknown
): string => {
  const parts: string[] = [];

  if (typeof payload.message === 'string' && payload.message.trim()) {
    parts.push(payload.message);
  }

  if (status) {
    parts.push(`Status: ${status}`);
  }

  if (payload.toolInput) {
    parts.push(`Input: ${stringifyPayload(payload.toolInput)}`);
  }

  if (parts.length > 0) {
    return parts.join('\n');
  }

  return stringifyPayload(fallbackValue ?? payload);
};

export const useChat = () => {
  const {
    messages,
    currentConversationId,
    isStreaming,
    streamStatus,
    streamingContent,
    thinkingSteps,
    workflowTrace,
    citations,
    error,
    knowledgeBaseEnabled,
    selectedKnowledgeBaseId,
    setMessages,
    addMessage,
    setCurrentConversationId,
    setStreamStatus,
    setStreamingContent,
    appendStreamingContent,
    addThinkingStep,
    clearThinkingSteps,
    mergeWorkflowTrace,
    clearWorkflowTrace,
    setCitations,
    setError,
    setKnowledgeBaseEnabled,
    setSelectedKnowledgeBaseId,
    reset,
  } = useChatStore();

  const { connect, cancel } = useSSE();
  const [isLoading, setIsLoading] = useState(false);
  const streamIdRef = useRef<string | null>(null);
  const hasReceivedContentChunkRef = useRef(false);
  const streamingContentRef = useRef(streamingContent);

  const isStreamBootstrapEvent = (value: unknown) => String(value || '').trim() === 'stream_started';

  const replaceStreamingContent = useCallback(
    (content: string) => {
      streamingContentRef.current = content;
      setStreamingContent(content);
    },
    [setStreamingContent]
  );

  const appendStreamingChunk = useCallback(
    (content: string) => {
      streamingContentRef.current += content;
      appendStreamingContent(content);
    },
    [appendStreamingContent]
  );

  const clearStreamingContent = useCallback(() => {
    streamingContentRef.current = '';
    setStreamingContent('');
  }, [setStreamingContent]);

  const finalizeAssistantMessage = useCallback(
    (conversationId: string, content: string, assistantMessageId?: string) => {
      const normalizedContent = content.trim();
      if (!conversationId || !normalizedContent) {
        return;
      }

      const currentMessages = useChatStore.getState().messages;
      if (assistantMessageId && currentMessages.some((item) => item.messageId === assistantMessageId)) {
        return;
      }

      addMessage({
        messageId: assistantMessageId ?? `assistant-${Date.now()}`,
        conversationId,
        messageType: 'assistant',
        content,
        sequenceNumber: currentMessages.length + 1,
        createdAt: new Date().toISOString(),
      });
    },
    [addMessage]
  );

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
        if (isStreaming && currentConversationId !== conversationId) {
          cancel();
          setStreamStatus('idle');
          streamIdRef.current = null;
          hasReceivedContentChunkRef.current = false;
        }
        clearThinkingSteps();
        clearWorkflowTrace();
        setCitations([]);
        clearStreamingContent();
        const response = await conversationService.getConversationMessages(conversationId);
        setCurrentConversationId(conversationId);
        setMessages(response.data);
      } catch (err: any) {
        setError(err.message || 'Load messages failed');
      } finally {
        setIsLoading(false);
      }
    },
    [
      cancel,
      clearStreamingContent,
      clearThinkingSteps,
      clearWorkflowTrace,
      isStreaming,
      setCitations,
      setCurrentConversationId,
      setError,
      setMessages,
      setStreamStatus,
    ]
  );

  const sendMessage = useCallback(
    async (question: string, conversationId?: string) => {
      const targetConversationId = conversationId || currentConversationId;

      setError(null);
      clearThinkingSteps();
      clearWorkflowTrace();
      clearStreamingContent();
      setStreamStatus('connecting');
      streamIdRef.current = null;
      hasReceivedContentChunkRef.current = false;

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
          const contentPayload = event.content && typeof event.content === 'object'
            ? adaptDoneEventContent(event.content)
            : {};
          const resolvedToolName = typeof streamMetadata.toolName === 'string'
            ? streamMetadata.toolName
            : typeof contentPayload.toolName === 'string'
              ? contentPayload.toolName
              : undefined;
          const requestId = typeof event.requestId === 'string'
            ? event.requestId
            : typeof streamMetadata.requestId === 'string'
              ? streamMetadata.requestId
              : undefined;
          const executionId = typeof event.executionId === 'string'
            ? event.executionId
            : typeof streamMetadata.executionId === 'string'
              ? streamMetadata.executionId
              : typeof contentPayload.executionId === 'string'
                ? contentPayload.executionId
                : undefined;

          mergeWorkflowTrace({
            workflowEngine: typeof streamMetadata.workflowEngine === 'string' ? streamMetadata.workflowEngine : undefined,
            workflowPath: Array.isArray(streamMetadata.workflowPath)
              ? streamMetadata.workflowPath.filter((value): value is string => typeof value === 'string')
              : undefined,
            fallbackReason: typeof streamMetadata.fallbackReason === 'string' ? streamMetadata.fallbackReason : undefined,
            errorCode: typeof streamMetadata.errorCode === 'string' ? streamMetadata.errorCode : undefined,
            errorType: typeof streamMetadata.errorType === 'string' ? streamMetadata.errorType : undefined,
            toolName: resolvedToolName,
            requestId,
            executionId,
            knowledgeBaseId: typeof streamMetadata.knowledgeBaseId === 'string' ? streamMetadata.knowledgeBaseId : undefined,
            documentId: typeof streamMetadata.documentId === 'string' ? streamMetadata.documentId : undefined,
          });

          const streamId = typeof streamMetadata.streamId === 'string'
            ? streamMetadata.streamId
            : undefined;
          if (streamId) {
            streamIdRef.current = streamId;
          }

          if (event.type !== 'done' && event.type !== 'error') {
            setStreamStatus('streaming');
          }

          switch (event.type) {
            case 'thinking': {
              const thinkingText = resolveThinkingText(event.message, event.content, contentPayload as Record<string, unknown>);
              if (!isStreamBootstrapEvent(thinkingText)) {
                const [title] = thinkingText.split('\n');
                addThinkingStep({
                  step: title || thinkingText,
                  description: thinkingText,
                  timestamp: event.timestamp,
                });
              }
              break;
            }
            case 'content':
              hasReceivedContentChunkRef.current = true;
              appendStreamingChunk(String(event.content || ''));
              break;
            case 'tool_call': {
              const toolStatus = typeof streamMetadata.status === 'string'
                ? streamMetadata.status
                : typeof contentPayload.status === 'string'
                  ? contentPayload.status
                  : undefined;
              addThinkingStep({
                step: resolveToolStepTitle(resolvedToolName, toolStatus),
                description: buildToolDescription(
                  contentPayload as Record<string, unknown>,
                  toolStatus,
                  event.content || event.metadata || {}
                ),
                timestamp: event.timestamp,
              });
              break;
            }
            case 'result': {
              const resultPayload = adaptDoneEventContent(event.content);
              if (resultPayload.citations) {
                setCitations(resultPayload.citations);
              }
              const resultText = extractResultText(resultPayload);
              const isStepResult = streamMetadata.resultScope === 'step';
              if (!isStepResult && !hasReceivedContentChunkRef.current && resultText) {
                replaceStreamingContent(resultText);
              }
              break;
            }
            case 'error':
              setError(
                [
                  String(event.message || event.content || 'Message send failed'),
                  typeof streamMetadata.errorCode === 'string' ? `Error code: ${streamMetadata.errorCode}` : '',
                ]
                  .filter(Boolean)
                  .join(' | ')
              );
              setStreamStatus('error');
              streamIdRef.current = null;
              hasReceivedContentChunkRef.current = false;
              break;
            case 'done': {
              const doneData = adaptDoneEventContent(event.content);
              const doneConversationId = doneData.conversationId ?? event.conversationId ?? targetConversationId;
              const assistantMessageId = typeof doneData.assistantMessageId === 'string'
                ? doneData.assistantMessageId
                : undefined;
              const finalText = extractResultText(doneData) ?? streamingContentRef.current;

              if (doneData.citations) {
                setCitations(doneData.citations);
              }

              mergeWorkflowTrace({
                executionId: typeof doneData.executionId === 'string' ? doneData.executionId : executionId,
              });

              const finalizeLocally = () => {
                const fallbackConversationId = doneConversationId || targetConversationId || currentConversationId || '';
                if (finalText && fallbackConversationId) {
                  finalizeAssistantMessage(fallbackConversationId, finalText, assistantMessageId);
                }
                clearStreamingContent();
              };

              setStreamStatus('completed');

              if (doneConversationId) {
                setCurrentConversationId(doneConversationId);
                void refreshMessages(doneConversationId)
                  .then(() => {
                    clearStreamingContent();
                  })
                  .catch(() => {
                    finalizeLocally();
                  });
              } else {
                finalizeLocally();
              }
              streamIdRef.current = null;
              hasReceivedContentChunkRef.current = false;
              break;
            }
          }
        },
        (streamError) => {
          setError(streamError.message);
          setStreamStatus('error');
          streamIdRef.current = null;
          hasReceivedContentChunkRef.current = false;
        },
        () => {
          const currentStatus = useChatStore.getState().streamStatus;
          if (currentStatus === 'connecting' || currentStatus === 'streaming') {
            setStreamStatus('completed');
          }
          hasReceivedContentChunkRef.current = false;
        }
      );
    },
    [
      addMessage,
      addThinkingStep,
      appendStreamingChunk,
      clearStreamingContent,
      clearThinkingSteps,
      clearWorkflowTrace,
      connect,
      currentConversationId,
      finalizeAssistantMessage,
      knowledgeBaseEnabled,
      mergeWorkflowTrace,
      messages.length,
      refreshMessages,
      replaceStreamingContent,
      selectedKnowledgeBaseId,
      setCitations,
      setCurrentConversationId,
      setError,
      setStreamStatus,
    ]
  );

  const stopStreaming = useCallback(async () => {
    const streamId = streamIdRef.current;

    if (streamId) {
      try {
        await chatService.pauseStream(streamId);
      } finally {
        cancel();
      }
    } else {
      cancel();
    }

    streamIdRef.current = null;
    setStreamStatus('cancelled');
    hasReceivedContentChunkRef.current = false;
  }, [cancel, setStreamStatus]);

  return {
    messages,
    currentConversationId,
    isStreaming,
    streamStatus,
    streamingContent,
    thinkingSteps,
    workflowTrace,
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
