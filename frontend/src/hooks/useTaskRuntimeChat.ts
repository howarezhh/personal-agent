import { useCallback, useEffect, useRef, useState } from 'react';

import {
  adaptStreamEventMetadata,
  type Message,
  type ThinkingStep,
} from '@/types';
import {
  camelizeTaskRuntimeValue,
  adaptTaskRuntimeGoalFromUnknown,
  adaptTaskRuntimePlanFromUnknown,
  toTaskRuntimeSubmitRequestContract,
  type TaskRuntimeActionResult,
  type TaskRuntimePlan,
  type TaskRuntimePlanStep,
  type TaskRuntimeStepEvaluation,
  type TaskRuntimeStepObservation,
  type TaskRuntimeStatus,
  type TaskRuntimeSubmitRequest,
  type TaskRuntimeTermination,
} from '@/adapters/taskRuntimeAdapter';
import { API_PATHS } from '@/constants/api';
import { conversationService } from '@/services/conversationService';
import { taskRuntimeService } from '@/services/taskRuntimeService';
import { useChatStore } from '@/stores/chatStore';

import { useSSE } from './useSSE';

const DEFAULT_CONVERSATION_TITLE = '新对话';

/** 生成稳定的前端链路 ID，便于 prepare / stream 复用。 */
const buildRuntimeId = (prefix: string): string => {
  const uuidValue = globalThis.crypto?.randomUUID?.().replace(/-/g, '') ?? `${Date.now()}${Math.random().toString(16).slice(2)}`;
  return `${prefix}_${uuidValue}`;
};

/** 为自动创建的会话生成一个可读标题。 */
const buildConversationTitle = (userInput: string): string => {
  const normalizedInput = userInput.trim();
  if (!normalizedInput) {
    return DEFAULT_CONVERSATION_TITLE;
  }

  return normalizedInput.length > 20 ? `${normalizedInput.slice(0, 20)}...` : normalizedInput;
};

const normalizeText = (value: unknown): string => {
  if (typeof value === 'string') {
    return value.trim();
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return '';
};

/** 将计划压缩成前端可读摘要。 */
const summarizePlan = (plan: TaskRuntimePlan): string => {
  const summaryLines: string[] = [];

  if (plan.reasoning.trim()) {
    summaryLines.push(plan.reasoning.trim());
  }

  if (plan.steps.length > 0) {
    summaryLines.push(
      plan.steps
        .map((step, index) => `${index + 1}. ${step.title}${step.description ? `：${step.description}` : ''}`)
        .join('\n'),
    );
  }

  return summaryLines.join('\n\n') || '已生成执行计划。';
};

const resolveStageLabel = (stage?: string): string => {
  switch (stage) {
    case 'goal_parsing':
      return '目标解析';
    case 'planning':
      return '执行规划';
    case 'step_started':
      return '步骤启动';
    case 'step_observation':
      return '步骤结果';
    case 'step_evaluation':
      return '步骤评估';
    case 'goal_evaluation':
      return '目标评估';
    case 'replan':
      return '重规划';
    case 'termination':
      return '执行结束';
    default:
      return stage || '运行事件';
  }
};

const resolveStepKind = (stepType?: string): ThinkingStep['kind'] => {
  if (stepType === 'tool_call') {
    return 'tool';
  }
  if (stepType === 'synthesize_answer' || stepType === 'retrieve' || stepType === 'analyze') {
    return 'stage';
  }
  return 'detail';
};

const resolveStepTitle = (step?: Partial<TaskRuntimePlanStep>, fallbackStage?: string): string => {
  if (step?.title?.trim()) {
    return step.title.trim();
  }
  if (step?.stepType === 'tool_call') {
    return '工具调用';
  }
  if (step?.stepType === 'retrieve') {
    return '资料检索';
  }
  if (step?.stepType === 'analyze') {
    return '阶段分析';
  }
  if (step?.stepType === 'synthesize_answer') {
    return '生成答复';
  }
  return resolveStageLabel(fallbackStage);
};

const buildObservationDescription = (
  step: Partial<TaskRuntimePlanStep> | undefined,
  observation: TaskRuntimeStepObservation | undefined,
  fallbackMessage?: string,
): string => {
  const descriptionParts: string[] = [];
  const outputData = observation?.outputData ?? {};

  if (observation?.summary?.trim()) {
    descriptionParts.push(observation.summary.trim());
  } else if (fallbackMessage?.trim()) {
    descriptionParts.push(fallbackMessage.trim());
  }

  if (step?.stepType === 'retrieve') {
    const retrievedCount = typeof outputData.retrievedCount === 'number' ? outputData.retrievedCount : undefined;
    if (retrievedCount !== undefined) {
      descriptionParts.push(`已检索到 ${retrievedCount} 条资料。`);
    }
  }

  if (step?.stepType === 'tool_call') {
    const expression = normalizeText(outputData.expression);
    const result = normalizeText(outputData.result);
    if (expression && result) {
      descriptionParts.push(`计算结果：${expression} = ${result}`);
    }
  }

  if (step?.stepType === 'analyze') {
    const analysisSummary = normalizeText(outputData.analysisSummary);
    if (analysisSummary) {
      descriptionParts.push(analysisSummary);
    }
  }

  if (step?.stepType === 'synthesize_answer') {
    const finalOutput = normalizeText(outputData.finalOutput);
    if (finalOutput) {
      descriptionParts.push(finalOutput);
    }
  }

  if (observation?.errorMessage?.trim()) {
    descriptionParts.push(`错误：${observation.errorMessage.trim()}`);
  }

  return descriptionParts.join('\n') || fallbackMessage || '步骤已产出结果。';
};

const buildEvaluationDescription = (
  evaluation: TaskRuntimeStepEvaluation | undefined,
  fallbackMessage?: string,
): string => {
  const descriptionParts: string[] = [];

  if (evaluation?.reasoning?.trim()) {
    descriptionParts.push(evaluation.reasoning.trim());
  } else if (fallbackMessage?.trim()) {
    descriptionParts.push(fallbackMessage.trim());
  }

  if (typeof evaluation?.qualityScore === 'number') {
    descriptionParts.push(`质量分：${evaluation.qualityScore}`);
  }

  if (evaluation?.nextAction?.trim()) {
    descriptionParts.push(`后续动作：${evaluation.nextAction.trim()}`);
  }

  return descriptionParts.join('\n') || '步骤评估已完成。';
};

const resolveDoneText = (content: unknown, fallbackMessage?: string): string => {
  if (typeof content === 'string' && content.trim()) {
    return content.trim();
  }

  if (!content || typeof content !== 'object') {
    return fallbackMessage?.trim() || '';
  }

  const normalized = camelizeTaskRuntimeValue(content) as Record<string, unknown>;
  return normalizeText(normalized.finalOutput) || normalizeText(normalized.reason) || fallbackMessage?.trim() || '';
};

export const useTaskRuntimeChat = () => {
  const {
    messages,
    currentConversationId,
    isStreaming,
    streamStatus,
    streamingContent,
    thinkingSteps,
    workflowTrace,
    runtimeGoal,
    runtimePlan,
    runtimeTaskStatus,
    citations,
    error,
    knowledgeBaseEnabled,
    selectedKnowledgeBaseId,
    setMessages,
    addMessage,
    setCurrentConversationId,
    setStreamStatus,
    setStreamingContent,
    addThinkingStep,
    clearThinkingSteps,
    mergeWorkflowTrace,
    clearWorkflowTrace,
    setRuntimeGoal,
    setRuntimePlan,
    setRuntimeTaskStatus,
    clearRuntimeState,
    setCitations,
    setError,
    setKnowledgeBaseEnabled,
    setSelectedKnowledgeBaseId,
    reset,
  } = useChatStore();

  const { connect, cancel } = useSSE();
  const [isLoading, setIsLoading] = useState(false);
  const [taskActionLoading, setTaskActionLoading] = useState<'pause' | 'resume' | 'cancel' | 'retry' | null>(null);
  const streamingContentRef = useRef(streamingContent);
  const stopRequestedRef = useRef(false);
  const pendingCompletionSyncRef = useRef<{ conversationId: string; assistantText: string } | null>(null);
  const taskStatusPollingTimerRef = useRef<number | null>(null);

  useEffect(() => {
    streamingContentRef.current = streamingContent;
  }, [streamingContent]);

  const replaceStreamingContent = useCallback((content: string) => {
    streamingContentRef.current = content;
    setStreamingContent(content);
  }, [setStreamingContent]);

  const clearStreamingContent = useCallback(() => {
    streamingContentRef.current = '';
    setStreamingContent('');
  }, [setStreamingContent]);

  const notifyConversationUpdated = useCallback((conversationId: string) => {
    if (typeof window === 'undefined' || !conversationId) {
      return;
    }

    window.dispatchEvent(new CustomEvent('conversation:updated', { detail: { conversationId } }));
  }, []);

  const upsertTimelineStep = useCallback((step: ThinkingStep) => {
    addThinkingStep(step);
  }, [addThinkingStep]);

  const finalizeOpenSteps = useCallback((status: 'completed' | 'failed', timestamp: string, reason?: string) => {
    const activeSteps = useChatStore.getState().thinkingSteps.filter((step) => step.status === 'in_progress');
    activeSteps.forEach((step) => {
      upsertTimelineStep({
        ...step,
        status,
        timestamp,
        endedAt: timestamp,
        description: reason && status === 'failed'
          ? [step.description, `终止原因：${reason}`].filter(Boolean).join('\n')
          : step.description,
      });
    });
  }, [upsertTimelineStep]);

  const appendWorkflowStage = useCallback((stage?: string) => {
    if (!stage) {
      return;
    }

    const currentPath = Array.isArray(useChatStore.getState().workflowTrace.workflowPath)
      ? useChatStore.getState().workflowTrace.workflowPath as string[]
      : [];
    const nextPath = currentPath.includes(stage) ? currentPath : [...currentPath, stage];
    mergeWorkflowTrace({ workflowPath: nextPath, currentStage: stage });
  }, [mergeWorkflowTrace]);

  const refreshConversationMessages = useCallback(async (conversationId: string) => {
    // 统一回刷后端真实消息，覆盖本地乐观态，避免 message_id 与持久化结果漂移。
    const response = await conversationService.getConversationMessages(conversationId);
    setMessages(response.data);
    setCurrentConversationId(conversationId);
    notifyConversationUpdated(conversationId);
  }, [notifyConversationUpdated, setCurrentConversationId, setMessages]);

  const addGoalAndPlanPreview = useCallback((plan: TaskRuntimePlan, normalizedGoal: string, timestamp: string) => {
    upsertTimelineStep({
      id: `stage-goal-${plan.goalId}`,
      kind: 'stage',
      step: '目标解析',
      description: normalizedGoal ? `目标：${normalizedGoal}` : '已完成目标解析。',
      status: 'completed',
      timestamp,
      startedAt: timestamp,
      endedAt: timestamp,
      stage: 'goal_parsing',
    });
    upsertTimelineStep({
      id: `planning-${plan.planId}`,
      kind: 'stage',
      step: '执行规划',
      description: summarizePlan(plan),
      status: 'completed',
      timestamp,
      startedAt: timestamp,
      endedAt: timestamp,
      stage: 'planning',
    });
  }, [upsertTimelineStep]);

  /**
   * 把任务快照同步回 store，并顺手回填 goal / plan，确保页面和侧边栏看到的是同一份状态。
   */
  const applyTaskRuntimeStatus = useCallback((statusSnapshot: TaskRuntimeStatus | null) => {
    setRuntimeTaskStatus(statusSnapshot);
    if (!statusSnapshot) {
      return;
    }

    if (statusSnapshot.goal) {
      setRuntimeGoal(statusSnapshot.goal);
    }
    if (statusSnapshot.currentPlan) {
      setRuntimePlan(statusSnapshot.currentPlan);
    }
    mergeWorkflowTrace({
      requestId: statusSnapshot.requestId,
      executionId: statusSnapshot.executionId,
      planId: statusSnapshot.currentPlanId,
      stepId: statusSnapshot.currentStepId,
    });
  }, [mergeWorkflowTrace, setRuntimeGoal, setRuntimePlan, setRuntimeTaskStatus]);

  /**
   * 仅更新本地任务摘要字段，适合在 SSE 事件到达时快速刷新当前步骤和状态。
   */
  const patchTaskRuntimeStatus = useCallback((patch: Partial<TaskRuntimeStatus>) => {
    const currentStatusSnapshot = useChatStore.getState().runtimeTaskStatus;
    if (!currentStatusSnapshot) {
      return;
    }

    applyTaskRuntimeStatus({
      ...currentStatusSnapshot,
      ...patch,
    });
  }, [applyTaskRuntimeStatus]);

  const stopTaskStatusPolling = useCallback(() => {
    if (taskStatusPollingTimerRef.current !== null && typeof window !== 'undefined') {
      window.clearInterval(taskStatusPollingTimerRef.current);
      taskStatusPollingTimerRef.current = null;
    }
  }, []);

  /**
   * 拉取一次任务状态；轮询场景下默认静默失败，避免后端生命周期接口未落地时不断弹错。
   */
  const refreshTaskStatus = useCallback(async (
    taskId: string,
    options: { silent?: boolean } = {},
  ): Promise<TaskRuntimeStatus | null> => {
    try {
      const latestStatus = await taskRuntimeService.getTaskStatus(taskId);
      applyTaskRuntimeStatus(latestStatus);
      return latestStatus;
    } catch (requestError: any) {
      const statusCode = requestError?.response?.status;
      if (options.silent || statusCode === 404 || statusCode === 501) {
        return null;
      }

      setError(requestError.message || '获取任务状态失败');
      return null;
    }
  }, [applyTaskRuntimeStatus, setError]);

  /**
   * 当任务进入长生命周期后，用轮询补齐暂停/恢复/终态验收等非流式信息。
   */
  const startTaskStatusPolling = useCallback((taskId: string) => {
    if (typeof window === 'undefined' || !taskId) {
      return;
    }

    stopTaskStatusPolling();
    taskStatusPollingTimerRef.current = window.setInterval(() => {
      void refreshTaskStatus(taskId, { silent: true });
    }, 3000);
  }, [refreshTaskStatus, stopTaskStatusPolling]);

  const syncTaskStatusFromAction = useCallback(async (
    actionResult: TaskRuntimeActionResult,
  ) => {
    const currentStatusSnapshot = useChatStore.getState().runtimeTaskStatus;
    const mergedStatusSnapshot: TaskRuntimeStatus = {
      ...(currentStatusSnapshot ?? {
        requestId: actionResult.requestId,
        executionId: actionResult.executionId,
        status: actionResult.status,
        metadata: {},
        artifacts: [],
      }),
      taskId: actionResult.taskId ?? currentStatusSnapshot?.taskId,
      requestId: actionResult.requestId,
      executionId: actionResult.executionId,
      status: actionResult.status,
      checkpointId: actionResult.checkpointId ?? currentStatusSnapshot?.checkpointId,
      currentPlanId: actionResult.currentPlanId ?? currentStatusSnapshot?.currentPlanId,
      currentStepId: actionResult.currentStepId ?? currentStatusSnapshot?.currentStepId,
      createdAt: actionResult.createdAt ?? currentStatusSnapshot?.createdAt,
      updatedAt: actionResult.updatedAt ?? currentStatusSnapshot?.updatedAt,
      metadata: actionResult.metadata ?? currentStatusSnapshot?.metadata ?? {},
      goal: currentStatusSnapshot?.goal,
      currentPlan: currentStatusSnapshot?.currentPlan,
      termination: currentStatusSnapshot?.termination,
      latestCheckpoint: currentStatusSnapshot?.latestCheckpoint,
      artifacts: currentStatusSnapshot?.artifacts ?? [],
      evaluationReport: currentStatusSnapshot?.evaluationReport,
    };

    applyTaskRuntimeStatus(mergedStatusSnapshot);
    if (mergedStatusSnapshot.taskId) {
      await refreshTaskStatus(mergedStatusSnapshot.taskId, { silent: true });
    }
  }, [applyTaskRuntimeStatus, refreshTaskStatus]);

  const loadMessages = useCallback(async (conversationId: string) => {
    try {
      setIsLoading(true);

      // 如果当前会话正在 task-runtime 流式执行，则保留前端本地态，不回放后台旧消息覆盖它。
      if (isStreaming && currentConversationId === conversationId) {
        setCurrentConversationId(conversationId);
        return;
      }

      if (isStreaming && currentConversationId !== conversationId) {
        stopRequestedRef.current = true;
        cancel();
        setStreamStatus('idle');
      }

      clearThinkingSteps();
      clearWorkflowTrace();
      clearRuntimeState();
      stopTaskStatusPolling();
      setCitations([]);
      clearStreamingContent();

      const response = await conversationService.getConversationMessages(conversationId);
      setCurrentConversationId(conversationId);
      setMessages(response.data);
    } catch (requestError: any) {
      setError(requestError.message || '加载会话消息失败');
    } finally {
      setIsLoading(false);
    }
  }, [
    cancel,
    clearRuntimeState,
    clearStreamingContent,
    clearThinkingSteps,
    clearWorkflowTrace,
    currentConversationId,
    isStreaming,
    setCitations,
    setCurrentConversationId,
    setError,
    setMessages,
    setStreamStatus,
    stopTaskStatusPolling,
  ]);

  const sendMessage = useCallback(async (userInput: string, conversationId?: string) => {
    const normalizedInput = userInput.trim();
    if (!normalizedInput) {
      return;
    }

    setError(null);
    clearThinkingSteps();
    clearWorkflowTrace();
    clearRuntimeState();
    stopTaskStatusPolling();
    clearStreamingContent();
    setCitations([]);
    setStreamStatus('connecting');
    setTaskActionLoading(null);
    stopRequestedRef.current = false;
    pendingCompletionSyncRef.current = null;

    const previousMessagesSnapshot = useChatStore.getState().messages;
    let preparationCompleted = false;

    try {
      let resolvedConversationId = conversationId || currentConversationId;
      if (!resolvedConversationId) {
        const conversation = await conversationService.createConversation({
          title: buildConversationTitle(normalizedInput),
        });
        resolvedConversationId = conversation.conversationId;
        setCurrentConversationId(resolvedConversationId);
        setMessages([]);
        notifyConversationUpdated(resolvedConversationId);
      }

      const requestId = buildRuntimeId('req');
      const messageId = buildRuntimeId('msg');
      const now = new Date().toISOString();
      const previousUserMessage = [...previousMessagesSnapshot]
        .reverse()
        .find((message) => message.messageType === 'user' && message.content.trim())?.content;
      const recentMessages = previousMessagesSnapshot.slice(-6).map((message) => ({
        message_type: message.messageType,
        content: message.content,
        message_id: message.messageId,
      }));

      const currentMessages = useChatStore.getState().messages;
      const userMessage: Message = {
        messageId,
        conversationId: resolvedConversationId,
        messageType: 'user',
        content: normalizedInput,
        sequenceNumber: currentMessages.length + 1,
        createdAt: now,
      };
      addMessage(userMessage);

      const request: TaskRuntimeSubmitRequest = {
        conversationId: resolvedConversationId,
        userInput: normalizedInput,
        messageId,
        requestId,
        metadata: {
          enable_knowledge_base: knowledgeBaseEnabled,
          knowledge_base_id: selectedKnowledgeBaseId || undefined,
          previous_user_message: previousUserMessage || undefined,
          recent_messages: recentMessages,
        },
      };

      const preparation = await taskRuntimeService.prepareTask(request);
      preparationCompleted = true;
      if (stopRequestedRef.current) {
        return;
      }

      applyTaskRuntimeStatus({
        ...preparation,
        goal: preparation.goal,
        currentPlan: preparation.plan,
        termination: undefined,
        latestCheckpoint: undefined,
        artifacts: [],
        evaluationReport: preparation.evaluationReport,
      });
      setRuntimeGoal(preparation.goal);
      setRuntimePlan(preparation.plan);
      mergeWorkflowTrace({
        runtimeMode: 'task_runtime',
        workflowEngine: 'builtin',
        workflowPath: ['goal_parsing', 'planning'],
        currentStage: 'planning',
        requestId: preparation.requestId,
        executionId: preparation.executionId,
        goalId: preparation.goal.goalId,
        planId: preparation.plan.planId,
        stepId: undefined,
        checkpointGraphName: undefined,
        checkpointThreadId: undefined,
        knowledgeBaseId: selectedKnowledgeBaseId || undefined,
      });
      addGoalAndPlanPreview(preparation.plan, preparation.goal.normalizedGoal, now);
      if (preparation.taskId) {
        startTaskStatusPolling(preparation.taskId);
      }

      await connect(
        API_PATHS.taskRuntime.stream,
        toTaskRuntimeSubmitRequestContract(request),
        (event) => {
          const streamMetadata = adaptStreamEventMetadata(event.metadata);
          const stage = typeof streamMetadata.stage === 'string' ? streamMetadata.stage : undefined;
          const stepId = typeof streamMetadata.stepId === 'string' ? streamMetadata.stepId : undefined;
          const planId = typeof streamMetadata.planId === 'string' ? streamMetadata.planId : undefined;
          const requestTraceId = typeof event.requestId === 'string'
            ? event.requestId
            : typeof streamMetadata.requestId === 'string'
              ? streamMetadata.requestId
              : requestId;
          const executionTraceId = typeof event.executionId === 'string'
            ? event.executionId
            : typeof streamMetadata.executionId === 'string'
              ? streamMetadata.executionId
              : undefined;

          appendWorkflowStage(stage);
          mergeWorkflowTrace({
            runtimeMode: 'task_runtime',
            workflowEngine: 'builtin',
            requestId: requestTraceId,
            executionId: executionTraceId,
            currentStage: stage,
            planId,
            stepId,
            errorCode: typeof event.errorCode === 'string'
              ? event.errorCode
              : typeof streamMetadata.errorCode === 'string'
                ? streamMetadata.errorCode
                : undefined,
            checkpointGraphName: undefined,
            checkpointThreadId: undefined,
            knowledgeBaseId: selectedKnowledgeBaseId || undefined,
          });

          if (useChatStore.getState().streamStatus === 'connecting') {
            setStreamStatus('streaming');
          }

          if (stage === 'goal_parsing') {
            const nextGoal = adaptTaskRuntimeGoalFromUnknown(event.content);
            if (nextGoal) {
              setRuntimeGoal(nextGoal);
              patchTaskRuntimeStatus({ goal: nextGoal, updatedAt: event.timestamp });
              mergeWorkflowTrace({ goalId: nextGoal.goalId });
              upsertTimelineStep({
                id: `stage-goal-${nextGoal.goalId}`,
                kind: 'stage',
                step: '目标解析',
                description: nextGoal.normalizedGoal ? `目标：${nextGoal.normalizedGoal}` : (event.message || '已完成目标解析。'),
                status: 'completed',
                timestamp: event.timestamp,
                startedAt: event.timestamp,
                endedAt: event.timestamp,
                stage,
              });
            }
            return;
          }

          if (stage === 'planning' || stage === 'replan') {
            const nextPlan = adaptTaskRuntimePlanFromUnknown(event.content);
            if (nextPlan) {
              setRuntimePlan(nextPlan);
              patchTaskRuntimeStatus({
                currentPlan: nextPlan,
                currentPlanId: nextPlan.planId,
                updatedAt: event.timestamp,
              });
              mergeWorkflowTrace({ planId: nextPlan.planId });
              upsertTimelineStep({
                id: `${stage}-${nextPlan.planId}`,
                kind: 'stage',
                step: stage === 'replan' ? '重规划' : '执行规划',
                description: summarizePlan(nextPlan),
                status: 'completed',
                timestamp: event.timestamp,
                startedAt: event.timestamp,
                endedAt: event.timestamp,
                stage,
              });
            }
            return;
          }

          if (stage === 'step_started') {
            const payload = event.content && typeof event.content === 'object'
              ? camelizeTaskRuntimeValue(event.content) as Record<string, unknown>
              : {};
            const step = payload.step && typeof payload.step === 'object'
              ? payload.step as Partial<TaskRuntimePlanStep>
              : useChatStore.getState().runtimePlan?.steps.find((item) => item.stepId === stepId);

            upsertTimelineStep({
              id: stepId || `step-started-${event.timestamp}`,
              kind: resolveStepKind(step?.stepType),
              step: resolveStepTitle(step, stage),
              description: step?.description || event.message || '步骤开始执行。',
              status: 'in_progress',
              timestamp: event.timestamp,
              startedAt: event.timestamp,
              stage,
            });
            patchTaskRuntimeStatus({
              status: 'running',
              currentPlanId: planId,
              currentStepId: stepId,
              updatedAt: event.timestamp,
            });
            return;
          }

          if (stage === 'step_observation') {
            if (Array.isArray(event.citations) && event.citations.length > 0) {
              setCitations(event.citations);
            }

            const runtimePlanState = useChatStore.getState().runtimePlan;
            const planStep = runtimePlanState?.steps.find((item) => item.stepId === stepId);

            if (typeof event.content === 'string') {
              if (planStep?.stepType === 'synthesize_answer') {
                replaceStreamingContent(event.content);
              }

              upsertTimelineStep({
                id: stepId || `step-observation-${event.timestamp}`,
                kind: resolveStepKind(planStep?.stepType),
                step: resolveStepTitle(planStep, stage),
                description: event.content,
                status: 'completed',
                timestamp: event.timestamp,
                startedAt: useChatStore.getState().thinkingSteps.find((item) => item.id === stepId)?.startedAt ?? event.timestamp,
                endedAt: event.timestamp,
                stage,
              });
              return;
            }

            const payload = event.content && typeof event.content === 'object'
              ? camelizeTaskRuntimeValue(event.content) as Record<string, unknown>
              : {};
            const step = payload.step && typeof payload.step === 'object'
              ? payload.step as Partial<TaskRuntimePlanStep>
              : planStep;
            const observation = payload.observation && typeof payload.observation === 'object'
              ? payload.observation as TaskRuntimeStepObservation
              : undefined;
            const status: ThinkingStep['status'] = observation?.success === false ? 'failed' : 'completed';

            upsertTimelineStep({
              id: stepId || `step-observation-${event.timestamp}`,
              kind: resolveStepKind(step?.stepType),
              step: resolveStepTitle(step, stage),
              description: buildObservationDescription(step, observation, event.message),
              status,
              timestamp: event.timestamp,
              startedAt: useChatStore.getState().thinkingSteps.find((item) => item.id === stepId)?.startedAt ?? event.timestamp,
              endedAt: event.timestamp,
              stage,
            });
            return;
          }

          if (stage === 'step_evaluation') {
            const payload = event.content && typeof event.content === 'object'
              ? camelizeTaskRuntimeValue(event.content) as Record<string, unknown>
              : {};
            const step = payload.step && typeof payload.step === 'object'
              ? payload.step as Partial<TaskRuntimePlanStep>
              : useChatStore.getState().runtimePlan?.steps.find((item) => item.stepId === stepId);
            const evaluation = payload.stepEvaluation && typeof payload.stepEvaluation === 'object'
              ? payload.stepEvaluation as TaskRuntimeStepEvaluation
              : undefined;

            upsertTimelineStep({
              id: `evaluation-${stepId || event.timestamp}`,
              kind: 'detail',
              step: `${resolveStepTitle(step, stage)} · 评估`,
              description: buildEvaluationDescription(evaluation, event.message),
              status: 'completed',
              timestamp: event.timestamp,
              startedAt: event.timestamp,
              endedAt: event.timestamp,
              stage,
            });
            return;
          }

          if (stage === 'goal_evaluation') {
            upsertTimelineStep({
              id: `goal-evaluation-${event.timestamp}`,
              kind: 'stage',
              step: '目标评估',
              description: event.message || '已完成整体目标评估。',
              status: 'completed',
              timestamp: event.timestamp,
              startedAt: event.timestamp,
              endedAt: event.timestamp,
              stage,
            });
            return;
          }

          if (event.type === 'done') {
            const finalText = resolveDoneText(event.content, event.message);
            const assistantText = finalText || event.message || '任务已完成。';
            if (Array.isArray(event.citations) && event.citations.length > 0) {
              setCitations(event.citations);
            }
            finalizeOpenSteps('completed', event.timestamp);
            upsertTimelineStep({
              id: `termination-${event.timestamp}`,
              kind: 'stage',
              step: '执行结束',
              description: event.message || '任务已完成。',
              status: 'completed',
              timestamp: event.timestamp,
              startedAt: event.timestamp,
              endedAt: event.timestamp,
              stage: 'termination',
            });
            if (assistantText) {
              replaceStreamingContent(assistantText);
            }
            patchTaskRuntimeStatus({
              status: 'succeeded',
              currentStepId: stepId,
              updatedAt: event.timestamp,
              termination: {
                status: 'succeeded',
                reason: event.message || '任务已完成。',
                finalOutput: assistantText,
              },
            });
            // done 只表示终止事件已送达；真正的持久化结果要等连接自然结束后再回刷。
            pendingCompletionSyncRef.current = {
              conversationId: resolvedConversationId,
              assistantText,
            };
            setStreamStatus('completed');
            return;
          }

          if (event.type === 'error') {
            pendingCompletionSyncRef.current = null;
            const termination = event.content && typeof event.content === 'object'
              ? camelizeTaskRuntimeValue(event.content) as TaskRuntimeTermination
              : undefined;
            const errorMessage = termination?.reason || event.message || '任务执行失败';
            mergeWorkflowTrace({
              errorCode: typeof event.errorCode === 'string'
                ? event.errorCode
                : typeof streamMetadata.errorCode === 'string'
                  ? streamMetadata.errorCode
                  : undefined,
            });
            finalizeOpenSteps('failed', event.timestamp, errorMessage);
            patchTaskRuntimeStatus({
              status: 'failed',
              updatedAt: event.timestamp,
              termination: {
                status: termination?.status || 'failed',
                reason: errorMessage,
                finalOutput: termination?.finalOutput,
                metadata: termination?.metadata,
              },
            });
            upsertTimelineStep({
              id: `termination-${event.timestamp}`,
              kind: 'stage',
              step: '执行结束',
              description: errorMessage,
              status: 'failed',
              timestamp: event.timestamp,
              startedAt: event.timestamp,
              endedAt: event.timestamp,
              stage: 'termination',
            });
            setError(errorMessage);
            setStreamStatus('error');
          }
        },
        (streamError) => {
          pendingCompletionSyncRef.current = null;
          const timestamp = new Date().toISOString();
          finalizeOpenSteps('failed', timestamp, streamError.message);
          patchTaskRuntimeStatus({
            status: 'failed',
            updatedAt: timestamp,
            termination: {
              status: 'failed',
              reason: streamError.message,
            },
          });
          upsertTimelineStep({
            id: `termination-${timestamp}`,
            kind: 'stage',
            step: '执行结束',
            description: streamError.message,
            status: 'failed',
            timestamp,
            startedAt: timestamp,
            endedAt: timestamp,
            stage: 'termination',
          });
          setError(streamError.message);
          setStreamStatus('error');
        },
        () => {
          const pendingCompletion = pendingCompletionSyncRef.current;
          const currentTaskId = useChatStore.getState().runtimeTaskStatus?.taskId;
          pendingCompletionSyncRef.current = null;
          if (pendingCompletion?.conversationId) {
            void refreshConversationMessages(pendingCompletion.conversationId)
              .catch(() => {
                // 历史消息回刷失败时，不再伪造本地 assistant 消息，
                // 后端持久化结果才是唯一事实源。
                setError('会话结果刷新失败，请稍后重试');
                notifyConversationUpdated(pendingCompletion.conversationId);
              })
              .finally(() => {
                clearStreamingContent();
                if (currentTaskId) {
                  void refreshTaskStatus(currentTaskId, { silent: true });
                }
              });
            return;
          }

          clearStreamingContent();
          if (currentTaskId) {
            void refreshTaskStatus(currentTaskId, { silent: true });
          }
          const currentStatus = useChatStore.getState().streamStatus;
          if (currentStatus === 'connecting' || currentStatus === 'streaming') {
            setStreamStatus('completed');
          }
        },
      );
    } catch (requestError: any) {
      pendingCompletionSyncRef.current = null;
      // 仅当 prepare 尚未成功时回滚乐观写入，避免把后端已持久化的用户消息误删。
      if (!preparationCompleted) {
        setMessages(previousMessagesSnapshot);
        clearStreamingContent();
      }
      const errorMessage = requestError.message || '任务运行时执行失败';
      setError(errorMessage);
      setStreamStatus('error');
    }
  }, [
    applyTaskRuntimeStatus,
    addGoalAndPlanPreview,
    addMessage,
    appendWorkflowStage,
    clearRuntimeState,
    clearStreamingContent,
    clearThinkingSteps,
    clearWorkflowTrace,
    connect,
    currentConversationId,
    finalizeOpenSteps,
    knowledgeBaseEnabled,
    mergeWorkflowTrace,
    patchTaskRuntimeStatus,
    refreshTaskStatus,
    notifyConversationUpdated,
    refreshConversationMessages,
    replaceStreamingContent,
    selectedKnowledgeBaseId,
    setCitations,
    setCurrentConversationId,
    setError,
    setMessages,
    setRuntimeGoal,
    setRuntimePlan,
    setStreamStatus,
    startTaskStatusPolling,
    stopTaskStatusPolling,
    upsertTimelineStep,
  ]);

  /**
   * 统一执行 pause / resume / cancel / retry，并把动作结果同步回前端状态。
   */
  const runTaskLifecycleAction = useCallback(async (
    action: 'pause' | 'resume' | 'cancel' | 'retry',
  ) => {
    const currentStatusSnapshot = useChatStore.getState().runtimeTaskStatus;
    const taskId = currentStatusSnapshot?.taskId;
    if (!taskId) {
      return;
    }

    const actionLabelMap = {
      pause: '暂停任务',
      resume: '恢复任务',
      cancel: '取消任务',
      retry: '重试任务',
    } as const;

    setError(null);
    setTaskActionLoading(action);
    try {
      // 暂停动作需要先终止当前 SSE 连接，避免前端继续消费旧流。
      if (action === 'pause') {
        pendingCompletionSyncRef.current = null;
        stopRequestedRef.current = true;
        cancel();
      }

      const actionResult = await taskRuntimeService.runTaskAction(taskId, action, {
        reason: `${actionLabelMap[action]}（前端触发）`,
      });
      await syncTaskStatusFromAction(actionResult);

      const timestamp = new Date().toISOString();
      const detailMessage = actionResult.detailMessage || `${actionLabelMap[action]}已提交。`;
      upsertTimelineStep({
        id: `task-action-${action}-${timestamp}`,
        kind: 'stage',
        step: actionLabelMap[action],
        description: detailMessage,
        status: 'completed',
        timestamp,
        startedAt: timestamp,
        endedAt: timestamp,
        stage: 'termination',
      });

      if (action === 'pause') {
        setStreamStatus('paused');
        return;
      }

      if (action === 'cancel') {
        stopTaskStatusPolling();
        finalizeOpenSteps('failed', timestamp, detailMessage || '任务已取消。');
        setStreamStatus('cancelled');
        return;
      }

      // resume / retry 依赖状态轮询获取新的终态和验收报告，因此这里只把流状态恢复为非错误态。
      setStreamStatus('completed');
    } catch (requestError: any) {
      setError(requestError.message || `${actionLabelMap[action]}失败`);
    } finally {
      setTaskActionLoading(null);
    }
  }, [
    cancel,
    finalizeOpenSteps,
    setError,
    setStreamStatus,
    stopTaskStatusPolling,
    syncTaskStatusFromAction,
    upsertTimelineStep,
  ]);

  useEffect(() => {
    const taskId = runtimeTaskStatus?.taskId;
    const taskStatusValue = runtimeTaskStatus?.status;
    if (!taskId || !taskStatusValue) {
      stopTaskStatusPolling();
      return undefined;
    }

    if (taskStatusValue === 'pending' || taskStatusValue === 'running' || taskStatusValue === 'paused') {
      startTaskStatusPolling(taskId);
    } else {
      stopTaskStatusPolling();
    }

    return undefined;
  }, [runtimeTaskStatus?.status, runtimeTaskStatus?.taskId, startTaskStatusPolling, stopTaskStatusPolling]);

  useEffect(() => () => {
    stopTaskStatusPolling();
  }, [stopTaskStatusPolling]);

  const pauseTask = useCallback(async () => {
    await runTaskLifecycleAction('pause');
  }, [runTaskLifecycleAction]);

  const resumeTask = useCallback(async () => {
    await runTaskLifecycleAction('resume');
  }, [runTaskLifecycleAction]);

  const cancelTask = useCallback(async () => {
    await runTaskLifecycleAction('cancel');
  }, [runTaskLifecycleAction]);

  const retryTask = useCallback(async () => {
    await runTaskLifecycleAction('retry');
  }, [runTaskLifecycleAction]);

  const stopStreaming = useCallback(() => {
    pendingCompletionSyncRef.current = null;
    stopRequestedRef.current = true;
    cancel();
    stopTaskStatusPolling();
    finalizeOpenSteps('failed', new Date().toISOString(), '用户手动停止了当前执行。');
    setStreamStatus('cancelled');
  }, [cancel, finalizeOpenSteps, setStreamStatus, stopTaskStatusPolling]);

  const resetRuntimeChat = useCallback(() => {
    stopTaskStatusPolling();
    setTaskActionLoading(null);
    reset();
  }, [reset, stopTaskStatusPolling]);

  return {
    messages,
    currentConversationId,
    isStreaming,
    streamStatus,
    streamingContent,
    thinkingSteps,
    workflowTrace,
    runtimeGoal,
    runtimePlan,
    runtimeTaskStatus,
    citations,
    error,
    isLoading,
    taskActionLoading,
    knowledgeBaseEnabled,
    selectedKnowledgeBaseId,
    loadMessages,
    sendMessage,
    pauseTask,
    resumeTask,
    cancelTask,
    retryTask,
    stopStreaming,
    setKnowledgeBaseEnabled,
    setSelectedKnowledgeBaseId,
    reset: resetRuntimeChat,
  };
};
