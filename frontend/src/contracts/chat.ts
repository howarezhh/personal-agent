import type { components } from './generated/openapi';

/**
 * Chat 前端契约。
 * 说明：这里只保留当前仍被主聊天页复用的 SSE / checkpoint 契约，
 * 已删除旧 `/api/v1/chat/ask` 发送链路相关手写 DTO。
 */

export type MessageContract = components['schemas']['ConversationMessageItem'];
export type SSEEventContract = components['schemas']['SSEEvent'] & {
  error_code?: string | null;
  citations?: CitationContract[] | null;
};

export interface CitationContract {
  source?: string;
  source_name?: string;
  content?: string;
  content_preview?: string;
  score?: number;
  relevance_score?: number;
  metadata?: Record<string, unknown>;
}

export interface ChatResultPayloadContract {
  status?: string;
  content?: string;
  final_step_key?: string;
  final_content?: string;
  step_count?: number;
  execution_id?: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  tool_params?: Record<string, unknown>;
  tool_call_id?: string;
  tool_calls?: Record<string, unknown>[];
  interpreted_result?: Record<string, unknown>;
  reasoning?: string;
  execution_time_ms?: number;
  route_decision?: Record<string, unknown>;
  retrieval_results?: Record<string, unknown>[];
  tool_result?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  citations?: CitationContract[];
}

export interface ChatDonePayloadContract extends ChatResultPayloadContract {
  conversation_id?: string;
  assistant_message_id?: string;
}

export interface CheckpointStateContract {
  graph_name: string;
  thread_id: string;
  checkpoint_thread_id?: string | null;
  values?: Record<string, unknown>;
  next?: string[];
  config?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
  created_at?: string | null;
  parent_config?: Record<string, unknown> | null;
  tasks?: unknown[];
  interrupts?: unknown[];
}

export interface CheckpointHistoryItemContract {
  config?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
  parent_config?: Record<string, unknown> | null;
  pending_writes?: unknown[] | null;
  checkpoint: Record<string, unknown>;
}

export interface CheckpointHistoryContract {
  graph_name: string;
  thread_id: string;
  checkpoint_thread_id?: string | null;
  items?: CheckpointHistoryItemContract[];
}

export interface ClearCheckpointResponseContract {
  graph_name: string;
  thread_id: string;
  cleared: boolean;
}

export interface SuccessEnvelopeContract<T> {
  code: number;
  message: string;
  data?: T | null;
  timestamp: string;
}

export type CheckpointStateEnvelopeContract = SuccessEnvelopeContract<CheckpointStateContract>;
export type CheckpointHistoryEnvelopeContract = SuccessEnvelopeContract<CheckpointHistoryContract>;
export type ClearCheckpointEnvelopeContract = SuccessEnvelopeContract<ClearCheckpointResponseContract>;
