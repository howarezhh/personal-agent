import {
  adaptTaskRuntimeActionResponse,
  adaptTaskRuntimePrepareResponse,
  adaptTaskRuntimeStatusResponse,
  toTaskRuntimeActionRequestContract,
  toTaskRuntimeSubmitRequestContract,
  type TaskRuntimeActionRequest,
  type TaskRuntimeActionResult,
  type TaskRuntimePreparation,
  type TaskRuntimeStatus,
  type TaskRuntimeSubmitRequest,
} from '@/adapters/taskRuntimeAdapter';
import {
  adaptCheckpointHistory,
  adaptCheckpointState,
  type CheckpointHistory,
  type CheckpointState,
} from '@/adapters/chatAdapter';
import type {
  TaskRuntimeActionResponseContract,
  TaskRuntimePrepareEnvelopeContract,
  TaskRuntimeStatusResponseContract,
} from '@/contracts/taskRuntime';
import type {
  CheckpointHistoryEnvelopeContract,
  CheckpointStateEnvelopeContract,
  ClearCheckpointEnvelopeContract,
} from '@/contracts/chat';
import { API_PATHS } from '@/constants/api';
import api from './api';

interface SuccessEnvelopeContract<TData> {
  data?: TData;
}

export const taskRuntimeService = {
  /**
   * 先调用同步准备接口，拿到目标与计划。
   * 这样前端可以在流式执行开始前，先展示一份稳定的初始计划。
   */
  async prepareTask(request: TaskRuntimeSubmitRequest): Promise<TaskRuntimePreparation> {
    const response = await api.post<TaskRuntimePrepareEnvelopeContract>(
      API_PATHS.taskRuntime.prepare,
      toTaskRuntimeSubmitRequestContract(request),
    );
    return adaptTaskRuntimePrepareResponse(response.data.data!);
  },

  /**
   * 查询任务状态快照。
   * 说明：窗口 4 通过该接口轮询任务生命周期、最终验收报告和产物列表。
   */
  async getTaskStatus(taskId: string): Promise<TaskRuntimeStatus> {
    const response = await api.get<SuccessEnvelopeContract<TaskRuntimeStatusResponseContract>>(
      API_PATHS.taskRuntime.status(taskId),
    );
    return adaptTaskRuntimeStatusResponse(response.data.data!);
  },

  /**
   * 读取 checkpoint 当前状态。
   * 说明：聊天页时间线面板已统一改走 `taskRuntimeService`，不再依赖旧 `chatService`。
   */
  async getCheckpointState(graphName: string, threadId: string): Promise<CheckpointState> {
    const response = await api.get<CheckpointStateEnvelopeContract>(API_PATHS.taskRuntime.checkpointState(graphName, threadId));
    return adaptCheckpointState(response.data.data!);
  },

  /** 读取 checkpoint 历史快照。 */
  async getCheckpointHistory(graphName: string, threadId: string, limit = 20): Promise<CheckpointHistory> {
    const response = await api.get<CheckpointHistoryEnvelopeContract>(API_PATHS.taskRuntime.checkpointHistory(graphName, threadId), {
      params: { limit },
    });
    return adaptCheckpointHistory(response.data.data!);
  },

  /** 清空 checkpoint。 */
  async clearCheckpoint(graphName: string, threadId: string): Promise<boolean> {
    const response = await api.delete<ClearCheckpointEnvelopeContract>(API_PATHS.taskRuntime.checkpointState(graphName, threadId));
    return !!response.data.data?.cleared;
  },

  /**
   * 统一执行任务生命周期动作，避免调用侧重复拼接 URL 和 DTO。
   */
  async runTaskAction(
    taskId: string,
    action: 'pause' | 'resume' | 'cancel' | 'retry',
    request: TaskRuntimeActionRequest = {},
  ): Promise<TaskRuntimeActionResult> {
    const pathResolver = {
      pause: API_PATHS.taskRuntime.pause,
      resume: API_PATHS.taskRuntime.resume,
      cancel: API_PATHS.taskRuntime.cancel,
      retry: API_PATHS.taskRuntime.retry,
    } as const;

    const response = await api.post<SuccessEnvelopeContract<TaskRuntimeActionResponseContract>>(
      pathResolver[action](taskId),
      toTaskRuntimeActionRequestContract(request),
    );
    return adaptTaskRuntimeActionResponse(response.data.data!);
  },
};
