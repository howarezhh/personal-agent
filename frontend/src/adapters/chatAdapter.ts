import type {
  ChatDonePayloadContract,
  ChatResultPayloadContract,
  CheckpointHistoryContract,
  CheckpointStateContract,
  MessageContract,
  SSEEventContract,
} from '@/contracts/chat';

export interface Message {
  messageId: string;
  conversationId: string;
  messageType: 'user' | 'assistant' | 'system';
  content: string;
  sequenceNumber: number;
  parentMessageId?: string;
  createdAt: string;
  metadata?: Record<string, unknown>;
  citations?: Citation[];
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
  errorCode?: string;
  citations?: Citation[];
}

export type StreamStatus = 'idle' | 'connecting' | 'streaming' | 'paused' | 'completed' | 'error' | 'cancelled';

export interface Citation {
  source: string;
  content: string;
  score?: number;
  metadata?: Record<string, unknown>;
}

const normalizeMessageMetadata = (metadata: unknown): Record<string, unknown> => {
  if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) {
    return {};
  }
  return metadata as Record<string, unknown>;
};

export interface ThinkingStep {
  id: string;
  kind: 'stage' | 'tool' | 'detail';
  step: string;
  description: string;
  status: 'in_progress' | 'completed' | 'failed';
  timestamp: string;
  startedAt?: string;
  endedAt?: string;
  stage?: string;
  toolName?: string;
  toolCallId?: string;
}

export interface WorkflowTrace {
  workflowEngine?: string;
  workflowPath?: string[];
  runtimeMode?: string;
  currentStage?: string;
  fallbackReason?: string;
  errorCode?: string;
  errorType?: string;
  toolName?: string;
  requestId?: string;
  executionId?: string;
  goalId?: string;
  planId?: string;
  stepId?: string;
  checkpointGraphName?: string;
  checkpointThreadId?: string;
  knowledgeBaseId?: string;
  documentId?: string;
}

export interface StreamEventMetadata {
  streamId?: string;
  workflowEngine?: string;
  workflowPath?: string[];
  fallbackReason?: string;
  errorCode?: string;
  errorType?: string;
  toolName?: string;
  status?: string;
  resultScope?: string;
  stepKey?: string;
  stepName?: string;
  toolCallId?: string;
  traceKind?: string;
  timelineId?: string;
  timelineKind?: string;
  title?: string;
  description?: string;
  stage?: string;
  requestId?: string;
  executionId?: string;
  checkpointGraphName?: string;
  checkpointThreadId?: string;
  knowledgeBaseId?: string;
  documentId?: string;
  [key: string]: unknown;
}

export interface ResultEventContent {
  status?: string;
  content?: string;
  finalStepKey?: string;
  finalContent?: string;
  stepCount?: number;
  executionId?: string;
  toolName?: string;
  toolInput?: Record<string, unknown>;
  toolParams?: Record<string, unknown>;
  toolCallId?: string;
  toolCalls?: Record<string, unknown>[];
  interpretedResult?: Record<string, unknown>;
  reasoning?: string;
  executionTimeMs?: number;
  routeDecision?: Record<string, unknown>;
  retrievalResults?: Record<string, unknown>[];
  toolResult?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  citations?: Citation[];
}

export interface DoneEventContent extends ResultEventContent {
  conversationId?: string;
  assistantMessageId?: string;
}

export interface CheckpointState {
  graphName: string;
  threadId: string;
  checkpointThreadId?: string;
  values: Record<string, unknown>;
  next: string[];
  config?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  createdAt?: string;
  parentConfig?: Record<string, unknown>;
  tasks: unknown[];
  interrupts: unknown[];
}

export interface CheckpointHistoryItem {
  config?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  parentConfig?: Record<string, unknown>;
  pendingWrites?: unknown[];
  checkpoint: Record<string, unknown>;
}

export interface CheckpointHistory {
  graphName: string;
  threadId: string;
  checkpointThreadId?: string;
  items: CheckpointHistoryItem[];
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

export const adaptMessage = (message: MessageContract): Message => {
  // 历史消息中的 metadata 是当前消息对象的真实扩展信息来源，
  // 刷新后引用、request_id、execution_id 都必须从这里恢复。
  const normalizedMetadata = normalizeMessageMetadata(message.metadata);
  const rawCitations = normalizedMetadata.citations;

  return {
    messageId: message.message_id,
    conversationId: message.conversation_id,
    messageType: normalizeMessageType(message.message_type),
    content: message.content,
    sequenceNumber: message.sequence_number,
    parentMessageId: message.parent_message_id ?? undefined,
    createdAt: message.created_at,
    metadata: normalizedMetadata,
    citations: Array.isArray(rawCitations)
      ? rawCitations.map((citation) => adaptCitation(citation))
      : undefined,
  };
};

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
  errorCode: event.error_code ?? undefined,
  citations: Array.isArray(event.citations)
    ? event.citations.map((citation) => adaptCitation(citation))
    : undefined,
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

export const adaptDoneEventContent = (
  content: ChatResultPayloadContract | ChatDonePayloadContract | unknown
): DoneEventContent => {
  if (!content || typeof content !== 'object') {
    return {};
  }

  const normalized = camelizeKeys(content) as {
    status?: unknown;
    content?: unknown;
    finalStepKey?: unknown;
    finalContent?: unknown;
    stepCount?: unknown;
    executionId?: unknown;
    toolName?: unknown;
    toolInput?: unknown;
    toolParams?: unknown;
    toolCallId?: unknown;
    toolCalls?: unknown;
    interpretedResult?: unknown;
    reasoning?: unknown;
    executionTimeMs?: unknown;
    routeDecision?: unknown;
    retrievalResults?: unknown;
    toolResult?: unknown;
    metadata?: unknown;
    citations?: unknown[];
    conversationId?: unknown;
    assistantMessageId?: unknown;
  };

  return {
    status: typeof normalized.status === 'string' ? normalized.status : undefined,
    content: typeof normalized.content === 'string' ? normalized.content : undefined,
    finalStepKey: typeof normalized.finalStepKey === 'string' ? normalized.finalStepKey : undefined,
    finalContent: typeof normalized.finalContent === 'string' ? normalized.finalContent : undefined,
    stepCount: typeof normalized.stepCount === 'number' ? normalized.stepCount : undefined,
    executionId: typeof normalized.executionId === 'string' ? normalized.executionId : undefined,
    toolName: typeof normalized.toolName === 'string' ? normalized.toolName : undefined,
    toolInput: normalized.toolInput && typeof normalized.toolInput === 'object'
      ? normalized.toolInput as Record<string, unknown>
      : undefined,
    toolParams: normalized.toolParams && typeof normalized.toolParams === 'object'
      ? normalized.toolParams as Record<string, unknown>
      : undefined,
    toolCallId: typeof normalized.toolCallId === 'string' ? normalized.toolCallId : undefined,
    toolCalls: Array.isArray(normalized.toolCalls)
      ? normalized.toolCalls.filter(
        (item): item is Record<string, unknown> => !!item && typeof item === 'object'
      )
      : undefined,
    interpretedResult: normalized.interpretedResult && typeof normalized.interpretedResult === 'object'
      ? normalized.interpretedResult as Record<string, unknown>
      : undefined,
    reasoning: typeof normalized.reasoning === 'string' ? normalized.reasoning : undefined,
    executionTimeMs: typeof normalized.executionTimeMs === 'number' ? normalized.executionTimeMs : undefined,
    routeDecision: normalized.routeDecision && typeof normalized.routeDecision === 'object'
      ? normalized.routeDecision as Record<string, unknown>
      : undefined,
    retrievalResults: Array.isArray(normalized.retrievalResults)
      ? normalized.retrievalResults.filter(
        (item): item is Record<string, unknown> => !!item && typeof item === 'object'
      )
      : undefined,
    toolResult: normalized.toolResult && typeof normalized.toolResult === 'object'
      ? normalized.toolResult as Record<string, unknown>
      : undefined,
    metadata: normalized.metadata && typeof normalized.metadata === 'object'
      ? normalized.metadata as Record<string, unknown>
      : undefined,
    conversationId: typeof normalized.conversationId === 'string' ? normalized.conversationId : undefined,
    assistantMessageId: typeof normalized.assistantMessageId === 'string' ? normalized.assistantMessageId : undefined,
    citations: Array.isArray(normalized.citations)
      ? normalized.citations.map((citation) => adaptCitation(citation))
      : undefined,
  };
};

export const adaptCheckpointState = (value: CheckpointStateContract): CheckpointState => {
  const normalized = camelizeKeys(value) as Record<string, unknown>;
  return {
    graphName: String(normalized.graphName ?? ''),
    threadId: String(normalized.threadId ?? ''),
    checkpointThreadId: typeof normalized.checkpointThreadId === 'string' ? normalized.checkpointThreadId : undefined,
    values: normalized.values && typeof normalized.values === 'object' ? normalized.values as Record<string, unknown> : {},
    next: Array.isArray(normalized.next) ? normalized.next.filter((item): item is string => typeof item === 'string') : [],
    config: normalized.config && typeof normalized.config === 'object' ? normalized.config as Record<string, unknown> : undefined,
    metadata: normalized.metadata && typeof normalized.metadata === 'object' ? normalized.metadata as Record<string, unknown> : undefined,
    createdAt: typeof normalized.createdAt === 'string' ? normalized.createdAt : undefined,
    parentConfig: normalized.parentConfig && typeof normalized.parentConfig === 'object' ? normalized.parentConfig as Record<string, unknown> : undefined,
    tasks: Array.isArray(normalized.tasks) ? normalized.tasks : [],
    interrupts: Array.isArray(normalized.interrupts) ? normalized.interrupts : [],
  };
};

export const adaptCheckpointHistory = (value: CheckpointHistoryContract): CheckpointHistory => {
  const normalized = camelizeKeys(value) as Record<string, unknown>;
  const items = Array.isArray(normalized.items) ? normalized.items : [];
  return {
    graphName: String(normalized.graphName ?? ''),
    threadId: String(normalized.threadId ?? ''),
    checkpointThreadId: typeof normalized.checkpointThreadId === 'string' ? normalized.checkpointThreadId : undefined,
    items: items.map((item) => {
      const normalizedItem = item && typeof item === 'object' ? item as Record<string, unknown> : {};
      return {
        config: normalizedItem.config && typeof normalizedItem.config === 'object'
          ? normalizedItem.config as Record<string, unknown>
          : undefined,
        metadata: normalizedItem.metadata && typeof normalizedItem.metadata === 'object'
          ? normalizedItem.metadata as Record<string, unknown>
          : undefined,
        parentConfig: normalizedItem.parentConfig && typeof normalizedItem.parentConfig === 'object'
          ? normalizedItem.parentConfig as Record<string, unknown>
          : undefined,
        pendingWrites: Array.isArray(normalizedItem.pendingWrites) ? normalizedItem.pendingWrites : undefined,
        checkpoint: normalizedItem.checkpoint && typeof normalizedItem.checkpoint === 'object'
          ? normalizedItem.checkpoint as Record<string, unknown>
          : {},
      };
    }),
  };
};


