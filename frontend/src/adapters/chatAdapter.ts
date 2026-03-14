import type { AskRequestContract, AskResponseContract, MessageContract, SSEEventContract } from '@/contracts/chat';

export interface Message {
  messageId: string;
  conversationId: string;
  messageType: 'user' | 'assistant' | 'system';
  content: string;
  sequenceNumber: number;
  parentMessageId?: string;
  createdAt: string;
}

export interface AskRequest {
  question: string;
  conversationId?: string;
  stream?: boolean;
  enableKnowledgeBase?: boolean;
  knowledgeBaseId?: string;
}

export interface AskResponse {
  conversationId: string;
  messageId: string;
  answer: string;
  executionId?: string;
}

export interface SSEEvent {
  type: 'thinking' | 'content' | 'error' | 'result' | 'tool_call' | 'done';
  message?: string;
  content?: unknown;
  metadata?: Record<string, unknown>;
  timestamp: string;
  requestId?: string;
  conversationId?: string;
  messageId?: string;
  executionId?: string;
}

export interface Citation {
  source: string;
  content: string;
  score?: number;
  metadata?: Record<string, unknown>;
}

export interface ThinkingStep {
  step: string;
  description: string;
  timestamp: string;
}

export interface StreamEventMetadata {
  streamId?: string;
  [key: string]: unknown;
}

export interface DoneEventContent {
  conversationId?: string;
  citations?: Citation[];
  [key: string]: unknown;
}

const normalizeMessageType = (messageType: string): Message['messageType'] => {
  if (messageType === 'user' || messageType === 'assistant' || messageType === 'system') {
    return messageType;
  }

  return 'assistant';
};

const toCamelCase = (value: string): string => value.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase());

const camelizeKeys = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map((item) => camelizeKeys(item));
  }

  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).reduce<Record<string, unknown>>((result, [key, entryValue]) => {
      result[toCamelCase(key)] = camelizeKeys(entryValue);
      return result;
    }, {});
  }

  return value;
};

export const adaptMessage = (message: MessageContract): Message => ({
  messageId: message.message_id,
  conversationId: message.conversation_id,
  messageType: normalizeMessageType(message.message_type),
  content: message.content,
  sequenceNumber: message.sequence_number,
  parentMessageId: message.parent_message_id ?? undefined,
  createdAt: message.created_at,
});

export const adaptAskResponse = (response: AskResponseContract): AskResponse => ({
  conversationId: response.conversation_id,
  messageId: response.message_id,
  answer: response.answer,
  executionId: response.execution_id ?? undefined,
});

export const adaptSSEEvent = (event: SSEEventContract): SSEEvent => ({
  type: event.type,
  message: event.message ?? undefined,
  content: event.content,
  metadata: event.metadata,
  timestamp: event.timestamp ?? new Date().toISOString(),
  requestId: event.request_id ?? undefined,
  conversationId: event.conversation_id ?? undefined,
  messageId: event.message_id ?? undefined,
  executionId: event.execution_id ?? undefined,
});

export const adaptStreamEventMetadata = (metadata?: Record<string, unknown>): StreamEventMetadata => {
  const normalized = metadata ? (camelizeKeys(metadata) as Record<string, unknown>) : {};
  return normalized as StreamEventMetadata;
};

const adaptCitation = (citation: unknown): Citation => {
  const normalized = citation && typeof citation === 'object'
    ? (camelizeKeys(citation) as Record<string, unknown>)
    : {};

  return {
    source: String(normalized.source ?? normalized.sourceName ?? ''),
    content: String(normalized.content ?? normalized.contentPreview ?? ''),
    score: typeof normalized.score === 'number'
      ? normalized.score
      : typeof normalized.relevanceScore === 'number'
        ? normalized.relevanceScore
        : undefined,
    metadata: normalized.metadata && typeof normalized.metadata === 'object'
      ? (normalized.metadata as Record<string, unknown>)
      : undefined,
  };
};

export const adaptDoneEventContent = (content: unknown): DoneEventContent => {
  if (!content || typeof content !== 'object') {
    return {};
  }

  const normalized = camelizeKeys(content) as DoneEventContent & { citations?: unknown[] };
  return {
    ...normalized,
    citations: Array.isArray(normalized.citations)
      ? normalized.citations.map((citation) => adaptCitation(citation))
      : undefined,
  };
};

export const toAskRequestContract = (request: AskRequest): AskRequestContract => ({
  question: request.question,
  conversation_id: request.conversationId,
  stream: request.stream ?? true,
  enable_knowledge_base: request.enableKnowledgeBase ?? false,
  knowledge_base_id: request.knowledgeBaseId,
});
