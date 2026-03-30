import type {
  TaskExecutionStatusContract,
  TaskRuntimeActionRequestContract,
  TaskRuntimeActionResponseContract,
  TaskRuntimeArtifactResponseContract,
  TaskRuntimeCheckpointResponseContract,
  TaskRuntimeEvaluationReportResponseContract,
  TaskRuntimeGoalResponseContract,
  TaskRuntimePlanResponseContract,
  TaskRuntimePlanStepResponseContract,
  TaskRuntimePrepareResponseContract,
  TaskRuntimeStatusResponseContract,
  TaskRuntimeSubmitRequestContract,
  TaskRuntimeTerminationResponseContract,
} from '@/contracts/taskRuntime';

/** 任务运行时提交请求。 */
export interface TaskRuntimeSubmitRequest {
  conversationId: string;
  userInput: string;
  messageId?: string;
  requestId?: string;
  metadata?: Record<string, unknown>;
}

/** 任务生命周期动作请求。 */
export interface TaskRuntimeActionRequest {
  reason?: string;
  metadata?: Record<string, unknown>;
}

/** 任务目标。 */
export interface TaskRuntimeGoal {
  goalId: string;
  conversationId: string;
  sourceMessageId?: string;
  originalUserInput: string;
  normalizedGoal: string;
  successCriteria: string[];
  constraints: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

/** 任务计划步骤。 */
export interface TaskRuntimePlanStep {
  stepId: string;
  stepType: string;
  title: string;
  description: string;
  dependsOn: string[];
  metadata: Record<string, unknown>;
}

/** 任务计划。 */
export interface TaskRuntimePlan {
  planId: string;
  goalId: string;
  version: number;
  reasoning: string;
  steps: TaskRuntimePlanStep[];
  metadata: Record<string, unknown>;
}

/** 任务执行摘要。 */
export interface TaskRuntimeExecutionSummary {
  taskId?: string;
  requestId: string;
  executionId: string;
  status: TaskExecutionStatusContract;
  checkpointId?: string;
  currentPlanId?: string;
  currentStepId?: string;
  createdAt?: string;
  updatedAt?: string;
  metadata: Record<string, unknown>;
}

/** 同步准备结果。 */
export interface TaskRuntimePreparation extends TaskRuntimeExecutionSummary {
  goal: TaskRuntimeGoal;
  plan: TaskRuntimePlan;
  evaluationReport?: TaskRuntimeEvaluationReport;
}

/** 步骤执行观测。 */
export interface TaskRuntimeStepObservation {
  stepId?: string;
  success?: boolean;
  summary?: string;
  errorMessage?: string;
  outputData?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

/** 步骤评估。 */
export interface TaskRuntimeStepEvaluation {
  stepId?: string;
  stepCompleted?: boolean;
  nextAction?: string;
  qualityScore?: number;
  reasoning?: string;
  metadata?: Record<string, unknown>;
}

/** 检查点。 */
export interface TaskRuntimeCheckpoint {
  checkpointId: string;
  taskId?: string;
  executionId?: string;
  status: TaskExecutionStatusContract;
  iterationCount: number;
  completedStepIds: string[];
  latestPlanId?: string;
  latestStepId?: string;
  checkpointReason: string;
  createdAt?: string;
  metadata: Record<string, unknown>;
}

/** 标准任务产物。 */
export interface TaskRuntimeArtifact {
  artifactId: string;
  artifactType: string;
  title: string;
  content?: unknown;
  sourcePlanId?: string;
  sourceStepId?: string;
  createdAt?: string;
  metadata: Record<string, unknown>;
}

/** 最终验收报告。 */
export interface TaskRuntimeEvaluationReport {
  reportId: string;
  taskId?: string;
  success: boolean;
  overallScore: number;
  summary: string;
  satisfiedCriteria: string[];
  missingCriteria: string[];
  risks: string[];
  recommendations: string[];
  createdAt?: string;
  metadata: Record<string, unknown>;
}

/** 终止决策。 */
export interface TaskRuntimeTermination {
  status?: string;
  reason?: string;
  finalOutput?: string;
  metadata?: Record<string, unknown>;
}

/** 任务状态快照。 */
export interface TaskRuntimeStatus extends TaskRuntimeExecutionSummary {
  goal?: TaskRuntimeGoal;
  currentPlan?: TaskRuntimePlan;
  termination?: TaskRuntimeTermination;
  latestCheckpoint?: TaskRuntimeCheckpoint;
  artifacts: TaskRuntimeArtifact[];
  evaluationReport?: TaskRuntimeEvaluationReport;
}

/** 任务动作执行结果。 */
export interface TaskRuntimeActionResult extends TaskRuntimeExecutionSummary {
  action: 'pause' | 'resume' | 'cancel' | 'retry';
  accepted: boolean;
  detailMessage: string;
}

const toCamelCase = (value: string): string => value.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase());

/**
 * 统一把后端 snake_case 对象转换为前端 camelCase。
 * 说明：task-runtime 的 SSE content 为动态结构，因此这里提供通用转换函数供 Hook 复用。
 */
export const camelizeTaskRuntimeValue = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map((item) => camelizeTaskRuntimeValue(item));
  }

  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).reduce<Record<string, unknown>>((result, [key, entryValue]) => {
      result[toCamelCase(key)] = camelizeTaskRuntimeValue(entryValue);
      return result;
    }, {});
  }

  return value;
};

const normalizeStatus = (value: string | undefined): TaskExecutionStatusContract => {
  if (
    value === 'pending'
    || value === 'running'
    || value === 'paused'
    || value === 'succeeded'
    || value === 'failed'
    || value === 'cancelled'
    || value === 'timed_out'
  ) {
    return value;
  }
  return 'pending';
};

export const adaptTaskRuntimeGoal = (
  goal: TaskRuntimeGoalResponseContract,
): TaskRuntimeGoal => ({
  goalId: goal.goal_id,
  conversationId: goal.conversation_id,
  sourceMessageId: goal.source_message_id ?? undefined,
  originalUserInput: goal.original_user_input,
  normalizedGoal: goal.normalized_goal,
  successCriteria: Array.isArray(goal.success_criteria) ? goal.success_criteria : [],
  constraints: goal.constraints ?? {},
  metadata: goal.metadata ?? {},
});

export const adaptTaskRuntimePlanStep = (
  step: TaskRuntimePlanStepResponseContract,
): TaskRuntimePlanStep => ({
  stepId: step.step_id,
  stepType: step.step_type,
  title: step.title,
  description: step.description ?? '',
  dependsOn: Array.isArray(step.depends_on) ? step.depends_on : [],
  metadata: step.metadata ?? {},
});

export const adaptTaskRuntimePlan = (
  plan: TaskRuntimePlanResponseContract,
): TaskRuntimePlan => ({
  planId: plan.plan_id,
  goalId: plan.goal_id,
  version: plan.version,
  reasoning: plan.reasoning ?? '',
  steps: Array.isArray(plan.steps) ? plan.steps.map(adaptTaskRuntimePlanStep) : [],
  metadata: plan.metadata ?? {},
});

export const adaptTaskRuntimeEvaluationReport = (
  report: TaskRuntimeEvaluationReportResponseContract,
): TaskRuntimeEvaluationReport => ({
  reportId: report.report_id,
  taskId: report.task_id ?? undefined,
  success: report.success ?? false,
  overallScore: typeof report.overall_score === 'number' ? report.overall_score : 0,
  summary: report.summary ?? '',
  satisfiedCriteria: Array.isArray(report.satisfied_criteria) ? report.satisfied_criteria : [],
  missingCriteria: Array.isArray(report.missing_criteria) ? report.missing_criteria : [],
  risks: Array.isArray(report.risks) ? report.risks : [],
  recommendations: Array.isArray(report.recommendations) ? report.recommendations : [],
  createdAt: report.created_at ?? undefined,
  metadata: report.metadata ?? {},
});

export const adaptTaskRuntimeCheckpoint = (
  checkpoint: TaskRuntimeCheckpointResponseContract,
): TaskRuntimeCheckpoint => ({
  checkpointId: checkpoint.checkpoint_id,
  taskId: checkpoint.task_id ?? undefined,
  executionId: checkpoint.execution_id ?? undefined,
  status: normalizeStatus(checkpoint.status),
  iterationCount: typeof checkpoint.iteration_count === 'number' ? checkpoint.iteration_count : 0,
  completedStepIds: Array.isArray(checkpoint.completed_step_ids) ? checkpoint.completed_step_ids : [],
  latestPlanId: checkpoint.latest_plan_id ?? undefined,
  latestStepId: checkpoint.latest_step_id ?? undefined,
  checkpointReason: checkpoint.checkpoint_reason ?? '',
  createdAt: checkpoint.created_at ?? undefined,
  metadata: checkpoint.metadata ?? {},
});

export const adaptTaskRuntimeArtifact = (
  artifact: TaskRuntimeArtifactResponseContract,
): TaskRuntimeArtifact => ({
  artifactId: artifact.artifact_id,
  artifactType: artifact.artifact_type,
  title: artifact.title ?? '',
  content: artifact.content,
  sourcePlanId: artifact.source_plan_id ?? undefined,
  sourceStepId: artifact.source_step_id ?? undefined,
  createdAt: artifact.created_at ?? undefined,
  metadata: artifact.metadata ?? {},
});

export const adaptTaskRuntimeTermination = (
  termination: TaskRuntimeTerminationResponseContract,
): TaskRuntimeTermination => ({
  status: termination.status,
  reason: termination.reason,
  finalOutput: termination.final_output ?? undefined,
  metadata: termination.metadata ?? {},
});

export const adaptTaskRuntimeExecutionSummary = (
  summary: {
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
  },
): TaskRuntimeExecutionSummary => ({
  taskId: summary.task_id ?? undefined,
  requestId: summary.request_id,
  executionId: summary.execution_id,
  status: normalizeStatus(summary.status),
  checkpointId: summary.checkpoint_id ?? undefined,
  currentPlanId: summary.current_plan_id ?? undefined,
  currentStepId: summary.current_step_id ?? undefined,
  createdAt: summary.created_at ?? undefined,
  updatedAt: summary.updated_at ?? undefined,
  metadata: summary.metadata ?? {},
});

export const adaptTaskRuntimePrepareResponse = (
  response: TaskRuntimePrepareResponseContract,
): TaskRuntimePreparation => ({
  ...adaptTaskRuntimeExecutionSummary(response),
  goal: adaptTaskRuntimeGoal(response.goal),
  plan: adaptTaskRuntimePlan(response.plan),
  evaluationReport: response.evaluation_report
    ? adaptTaskRuntimeEvaluationReport(response.evaluation_report)
    : undefined,
});

export const adaptTaskRuntimeStatusResponse = (
  response: TaskRuntimeStatusResponseContract,
): TaskRuntimeStatus => ({
  ...adaptTaskRuntimeExecutionSummary(response),
  goal: response.goal ? adaptTaskRuntimeGoal(response.goal) : undefined,
  currentPlan: response.current_plan ? adaptTaskRuntimePlan(response.current_plan) : undefined,
  termination: response.termination ? adaptTaskRuntimeTermination(response.termination) : undefined,
  latestCheckpoint: response.latest_checkpoint
    ? adaptTaskRuntimeCheckpoint(response.latest_checkpoint)
    : undefined,
  artifacts: Array.isArray(response.artifacts) ? response.artifacts.map(adaptTaskRuntimeArtifact) : [],
  evaluationReport: response.evaluation_report
    ? adaptTaskRuntimeEvaluationReport(response.evaluation_report)
    : undefined,
});

export const adaptTaskRuntimeActionResponse = (
  response: TaskRuntimeActionResponseContract,
): TaskRuntimeActionResult => ({
  ...adaptTaskRuntimeExecutionSummary(response),
  action: response.action,
  accepted: response.accepted ?? true,
  detailMessage: response.detail_message ?? '',
});

export const adaptTaskRuntimeGoalFromUnknown = (value: unknown): TaskRuntimeGoal | null => {
  if (!value || typeof value !== 'object') {
    return null;
  }

  const normalized = camelizeTaskRuntimeValue(value) as Record<string, unknown>;
  if (typeof normalized.goalId !== 'string' || typeof normalized.conversationId !== 'string') {
    return null;
  }

  return {
    goalId: normalized.goalId,
    conversationId: normalized.conversationId,
    sourceMessageId: typeof normalized.sourceMessageId === 'string' ? normalized.sourceMessageId : undefined,
    originalUserInput: typeof normalized.originalUserInput === 'string' ? normalized.originalUserInput : '',
    normalizedGoal: typeof normalized.normalizedGoal === 'string' ? normalized.normalizedGoal : '',
    successCriteria: Array.isArray(normalized.successCriteria)
      ? normalized.successCriteria.filter((item): item is string => typeof item === 'string')
      : [],
    constraints: normalized.constraints && typeof normalized.constraints === 'object'
      ? normalized.constraints as Record<string, unknown>
      : {},
    metadata: normalized.metadata && typeof normalized.metadata === 'object'
      ? normalized.metadata as Record<string, unknown>
      : {},
  };
};

export const adaptTaskRuntimePlanFromUnknown = (value: unknown): TaskRuntimePlan | null => {
  if (!value || typeof value !== 'object') {
    return null;
  }

  const normalized = camelizeTaskRuntimeValue(value) as Record<string, unknown>;
  if (typeof normalized.planId !== 'string' || typeof normalized.goalId !== 'string') {
    return null;
  }

  const steps = Array.isArray(normalized.steps) ? normalized.steps : [];
  return {
    planId: normalized.planId,
    goalId: normalized.goalId,
    version: typeof normalized.version === 'number' ? normalized.version : 1,
    reasoning: typeof normalized.reasoning === 'string' ? normalized.reasoning : '',
    steps: steps
      .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
      .map((step) => ({
        stepId: typeof step.stepId === 'string' ? step.stepId : '',
        stepType: typeof step.stepType === 'string' ? step.stepType : '',
        title: typeof step.title === 'string' ? step.title : '',
        description: typeof step.description === 'string' ? step.description : '',
        dependsOn: Array.isArray(step.dependsOn) ? step.dependsOn.filter((item): item is string => typeof item === 'string') : [],
        metadata: step.metadata && typeof step.metadata === 'object' ? step.metadata as Record<string, unknown> : {},
      }))
      .filter((step) => !!step.stepId),
    metadata: normalized.metadata && typeof normalized.metadata === 'object'
      ? normalized.metadata as Record<string, unknown>
      : {},
  };
};

export const toTaskRuntimeSubmitRequestContract = (
  request: TaskRuntimeSubmitRequest,
): TaskRuntimeSubmitRequestContract => ({
  conversation_id: request.conversationId,
  user_input: request.userInput,
  message_id: request.messageId,
  request_id: request.requestId,
  metadata: request.metadata ?? {},
});

export const toTaskRuntimeActionRequestContract = (
  request: TaskRuntimeActionRequest,
): TaskRuntimeActionRequestContract => ({
  reason: request.reason,
  metadata: request.metadata ?? {},
});
