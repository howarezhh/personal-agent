import type { paths } from './generated/openapi';

/**
 * task-runtime 前端契约。
 * 说明：
 * 0. 当前模块不再维护“手写并行 DTO”作为独立权威来源，只保留生成契约上的前端映射收口；
 * 1. 已存在的 `/tasks` prepare 契约继续优先复用 OpenAPI 生成类型；
 * 2. 窗口 1 新增的生命周期 DTO 先以“后端契约映射类型”方式收敛；
 * 3. 后续待统一生成流程接入后，再替换为生成产物引用，避免长期并行漂移。
 */

type TaskRuntimePrepareOperation = paths['/api/v1/task-runtime/tasks']['post'];

type TaskRuntimePrepareRequestBody = NonNullable<TaskRuntimePrepareOperation['requestBody']>;

type TaskRuntimePrepareRequestContractRaw =
  TaskRuntimePrepareRequestBody['content']['application/json'];

type TaskRuntimePrepareSuccessResponse = NonNullable<
  TaskRuntimePrepareOperation['responses'][200]['content']['application/json']
>;

type TaskRuntimePreparePayload = NonNullable<TaskRuntimePrepareSuccessResponse['data']>;

type TaskRuntimePreparePlanSteps = NonNullable<TaskRuntimePreparePayload['plan']['steps']>;

export type TaskExecutionStatusContract =
  | 'pending'
  | 'running'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'timed_out';

export type TaskLifecycleActionContract = 'pause' | 'resume' | 'cancel' | 'retry';

export interface TaskRuntimeSubmitRequestContract
  extends Omit<TaskRuntimePrepareRequestContractRaw, 'message_id' | 'request_id' | 'metadata'> {
  message_id?: string | null;
  request_id?: string | null;
  metadata?: Record<string, unknown>;
}

export interface TaskRuntimeActionRequestContract {
  reason?: string | null;
  metadata?: Record<string, unknown>;
}

export interface TaskRuntimeExecutionSummaryResponseContract {
  task_id?: string | null;
  request_id: string;
  execution_id: string;
  status?: TaskExecutionStatusContract;
  checkpoint_id?: string | null;
  current_plan_id?: string | null;
  current_step_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  metadata?: Record<string, unknown>;
}

export type TaskRuntimeGoalResponseContract = TaskRuntimePreparePayload['goal'];

export type TaskRuntimePlanStepResponseContract = TaskRuntimePreparePlanSteps[number];

export type TaskRuntimePlanResponseContract = TaskRuntimePreparePayload['plan'];

export interface TaskRuntimeCheckpointResponseContract {
  checkpoint_id: string;
  task_id?: string | null;
  execution_id?: string | null;
  status?: TaskExecutionStatusContract;
  iteration_count?: number;
  completed_step_ids?: string[];
  latest_plan_id?: string | null;
  latest_step_id?: string | null;
  checkpoint_reason?: string;
  created_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface TaskRuntimeArtifactResponseContract {
  artifact_id: string;
  artifact_type: string;
  title?: string;
  content?: unknown;
  source_plan_id?: string | null;
  source_step_id?: string | null;
  created_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface TaskRuntimeEvaluationReportResponseContract {
  report_id: string;
  task_id?: string | null;
  success?: boolean;
  overall_score?: number;
  summary?: string;
  satisfied_criteria?: string[];
  missing_criteria?: string[];
  risks?: string[];
  recommendations?: string[];
  created_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface TaskRuntimeTerminationResponseContract {
  status: string;
  reason: string;
  final_output?: string | null;
  metadata?: Record<string, unknown>;
}

export interface TaskRuntimePrepareResponseContract extends TaskRuntimeExecutionSummaryResponseContract {
  goal: TaskRuntimeGoalResponseContract;
  plan: TaskRuntimePlanResponseContract;
  evaluation_report?: TaskRuntimeEvaluationReportResponseContract | null;
}

export interface TaskRuntimeStatusResponseContract extends TaskRuntimeExecutionSummaryResponseContract {
  goal?: TaskRuntimeGoalResponseContract | null;
  current_plan?: TaskRuntimePlanResponseContract | null;
  termination?: TaskRuntimeTerminationResponseContract | null;
  latest_checkpoint?: TaskRuntimeCheckpointResponseContract | null;
  artifacts?: TaskRuntimeArtifactResponseContract[];
  evaluation_report?: TaskRuntimeEvaluationReportResponseContract | null;
}

export interface TaskRuntimeActionResponseContract extends TaskRuntimeExecutionSummaryResponseContract {
  action: TaskLifecycleActionContract;
  accepted?: boolean;
  detail_message?: string;
}

export type TaskRuntimePrepareEnvelopeContract = TaskRuntimePrepareSuccessResponse;
