/**
 * 对话状态管理
 */

import { create } from 'zustand';
import { Message, Citation, ThinkingStep, WorkflowTrace, StreamStatus } from '@/types';

const CURRENT_CONVERSATION_STORAGE_KEY = 'current_conversation_id';
const SELECTED_KNOWLEDGE_BASE_STORAGE_KEY = 'selected_knowledge_base_id';

const getInitialConversationId = (): string | null => {
  if (typeof window === 'undefined') {
    return null;
  }

  return window.localStorage.getItem(CURRENT_CONVERSATION_STORAGE_KEY);
};

const getInitialKnowledgeBaseId = (): string | null => {
  if (typeof window === 'undefined') {
    return null;
  }

  return window.localStorage.getItem(SELECTED_KNOWLEDGE_BASE_STORAGE_KEY);
};

interface ChatState {
  messages: Message[];
  currentConversationId: string | null;
  isStreaming: boolean;
  streamStatus: StreamStatus;
  streamingContent: string;
  thinkingSteps: ThinkingStep[];
  workflowTrace: WorkflowTrace;
  citations: Citation[];
  error: string | null;
  knowledgeBaseEnabled: boolean;
  selectedKnowledgeBaseId: string | null;

  setMessages: (messages: Message[]) => void;
  addMessage: (message: Message) => void;
  setCurrentConversationId: (id: string | null) => void;
  setStreamStatus: (status: StreamStatus) => void;
  setStreamingContent: (content: string) => void;
  appendStreamingContent: (content: string) => void;
  addThinkingStep: (step: ThinkingStep) => void;
  clearThinkingSteps: () => void;
  setWorkflowTrace: (trace: WorkflowTrace) => void;
  mergeWorkflowTrace: (trace: Partial<WorkflowTrace>) => void;
  clearWorkflowTrace: () => void;
  setCitations: (citations: Citation[]) => void;
  setError: (error: string | null) => void;
  setKnowledgeBaseEnabled: (enabled: boolean) => void;
  setSelectedKnowledgeBaseId: (id: string | null) => void;
  reset: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  currentConversationId: getInitialConversationId(),
  isStreaming: false,
  streamStatus: 'idle',
  streamingContent: '',
  thinkingSteps: [],
  workflowTrace: {},
  citations: [],
  error: null,
  selectedKnowledgeBaseId: getInitialKnowledgeBaseId(),
  knowledgeBaseEnabled: !!getInitialKnowledgeBaseId(),

  setMessages: (messages) => set({ messages }),
  addMessage: (message) => set((state) => ({ messages: [...state.messages, message] })),
  setCurrentConversationId: (id) => {
    if (typeof window !== 'undefined') {
      if (id) {
        window.localStorage.setItem(CURRENT_CONVERSATION_STORAGE_KEY, id);
      } else {
        window.localStorage.removeItem(CURRENT_CONVERSATION_STORAGE_KEY);
      }
    }

    set({ currentConversationId: id });
  },
  setStreamStatus: (streamStatus) => set({
    streamStatus,
    isStreaming: streamStatus === 'connecting' || streamStatus === 'streaming',
  }),
  setStreamingContent: (content) => set({ streamingContent: content }),
  appendStreamingContent: (content) =>
    set((state) => ({ streamingContent: state.streamingContent + content })),
  addThinkingStep: (step) =>
    set((state) => ({ thinkingSteps: [...state.thinkingSteps, step] })),
  clearThinkingSteps: () => set({ thinkingSteps: [] }),
  setWorkflowTrace: (workflowTrace) => set({ workflowTrace }),
  mergeWorkflowTrace: (trace) => {
    const definedEntries = Object.entries(trace).filter(([, value]) => value !== undefined);
    if (definedEntries.length === 0) {
      return;
    }

    set((state) => ({
      workflowTrace: {
        ...state.workflowTrace,
        ...Object.fromEntries(definedEntries),
      },
    }));
  },
  clearWorkflowTrace: () => set({ workflowTrace: {} }),
  setCitations: (citations) => set({ citations }),
  setError: (error) => set({ error }),
  setKnowledgeBaseEnabled: (enabled) =>
    set((state) => ({
      knowledgeBaseEnabled: enabled,
      selectedKnowledgeBaseId: enabled ? state.selectedKnowledgeBaseId : null,
    })),
  setSelectedKnowledgeBaseId: (id) => {
    if (typeof window !== 'undefined') {
      if (id) {
        window.localStorage.setItem(SELECTED_KNOWLEDGE_BASE_STORAGE_KEY, id);
      } else {
        window.localStorage.removeItem(SELECTED_KNOWLEDGE_BASE_STORAGE_KEY);
      }
    }

    set({
      selectedKnowledgeBaseId: id,
      knowledgeBaseEnabled: !!id,
    });
  },
  reset: () => {
    if (typeof window !== 'undefined') {
      window.localStorage.removeItem(CURRENT_CONVERSATION_STORAGE_KEY);
      window.localStorage.removeItem(SELECTED_KNOWLEDGE_BASE_STORAGE_KEY);
    }

    set({
      messages: [],
      currentConversationId: null,
      isStreaming: false,
      streamStatus: 'idle',
      streamingContent: '',
      thinkingSteps: [],
      workflowTrace: {},
      citations: [],
      error: null,
      knowledgeBaseEnabled: false,
      selectedKnowledgeBaseId: null,
    });
  },
}));
