import { useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Modal,
  Space,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd';
import {
  ApartmentOutlined,
  CheckCircleOutlined,
  ClearOutlined,
  ExclamationCircleOutlined,
  EyeOutlined,
  HistoryOutlined,
  LoadingOutlined,
  PlayCircleOutlined,
  ToolOutlined,
} from '@ant-design/icons';

import { taskRuntimeService } from '@/services/taskRuntimeService';
import type { CheckpointHistory, CheckpointState, StreamStatus, ThinkingStep, WorkflowTrace } from '@/types';

interface ExecutionTimelinePanelProps {
  steps: ThinkingStep[];
  trace: WorkflowTrace;
  status?: StreamStatus;
  isStreaming?: boolean;
  checkpointGraphName?: string;
  checkpointThreadId?: string | null;
  onResumeCheckpoint?: (graphName: string, threadId: string) => Promise<void> | void;
}

const STATUS_LABELS: Record<StreamStatus, string> = {
  idle: '空闲',
  connecting: '连接中',
  streaming: '生成中',
  paused: '已暂停',
  completed: '已完成',
  error: '失败',
  cancelled: '已取消',
};

const STATUS_COLORS: Record<StreamStatus, string> = {
  idle: 'default',
  connecting: 'processing',
  streaming: 'blue',
  paused: 'warning',
  completed: 'success',
  error: 'error',
  cancelled: 'warning',
};

const STAGE_LABELS: Record<string, string> = {
  intent_recognition: '意图识别',
  retrieval: '知识检索',
  tool_call: '工具调用',
  generation: '答案生成',
  multi_agent: '多 Agent 协作',
  goal_parsing: '目标解析',
  planning: '执行规划',
  step_started: '步骤启动',
  step_observation: '步骤结果',
  step_evaluation: '步骤评估',
  goal_evaluation: '目标评估',
  replan: '重规划',
  termination: '执行结束',
};

const STAGE_DESCRIPTIONS: Record<string, string> = {
  intent_recognition: '分析用户问题，并决定本次请求的主执行分支。',
  retrieval: '从知识库或文档中检索上下文，准备回答所需信息。',
  tool_call: '调用外部工具或服务，补充回答所需数据。',
  generation: '综合上下文与工具结果，生成最终答案。',
  multi_agent: '按多 Agent 编排流程执行复杂任务。',
  goal_parsing: '把用户输入归一化为可执行目标，并提取成功标准。',
  planning: '生成首版执行计划，明确步骤顺序与依赖关系。',
  step_started: '某个计划步骤已进入执行状态。',
  step_observation: '某个计划步骤已返回观测结果。',
  step_evaluation: '对单步结果进行质量评估，并决定下一动作。',
  goal_evaluation: '对整体目标是否完成进行统一评估。',
  replan: '当前计划不足时，生成新的后续执行计划。',
  termination: '任务运行时已给出终止结论。',
};

const FALLBACK_REASON_LABELS: Record<string, string> = {
  unknown_router_action: '路由返回了未知动作，已回退到安全分支。',
  knowledge_base_disabled: '知识库开关关闭，已回退到直接回答。',
  retrieval_no_result: '未检索到有效结果，已回退到通用回答。',
  tool_route_to_retrieval: '无需调用工具，已切换到检索流程。',
  tool_not_needed: '无需调用工具，已直接生成回答。',
  tool_failure: '工具调用失败，已回退到通用回答。',
  tool_error_fallback: '工具执行异常，已回退到通用回答。',
  tool_result_missing: '工具未返回结果，已回退到通用回答。',
  workflow_policy_sanitized: '工作流已按运行时策略自动收敛。',
  workflow_policy_fallback: '工作流配置无效，已回退到安全默认配置。',
  default_workflow_config: '未提供有效工作流配置，已使用默认配置。',
};

const ENGINE_LABELS: Record<string, string> = {
  builtin: '内置规划器',
  langgraph: 'LangGraph',
};

const toStageLabel = (stage: string): string => STAGE_LABELS[stage] ?? stage;
const toStageDescription = (stage: string): string => STAGE_DESCRIPTIONS[stage] ?? '执行该阶段对应的工作流步骤。';
const toEngineLabel = (workflowEngine?: string): string | undefined => workflowEngine ? (ENGINE_LABELS[workflowEngine] ?? workflowEngine) : undefined;
const toFallbackLabel = (fallbackReason?: string): string | undefined => fallbackReason ? (FALLBACK_REASON_LABELS[fallbackReason] ?? fallbackReason) : undefined;

const formatTimestamp = (value?: string): string | undefined => {
  if (!value) {
    return undefined;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return undefined;
  }

  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
};

const renderJsonContent = (value: unknown) => (
  <pre style={{ margin: 0, maxHeight: 420, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
    {JSON.stringify(value, null, 2)}
  </pre>
);

export const ExecutionTimelinePanel = ({
  steps,
  trace,
  status = 'idle',
  isStreaming = false,
  checkpointGraphName,
  checkpointThreadId,
  onResumeCheckpoint,
}: ExecutionTimelinePanelProps) => {
  const [modalApi, contextHolder] = Modal.useModal();
  const [messageApi, messageContextHolder] = message.useMessage();
  const [checkpointLoading, setCheckpointLoading] = useState<'state' | 'history' | 'resume' | 'clear' | null>(null);

  const workflowPath = Array.isArray(trace.workflowPath) ? trace.workflowPath : [];
  const fallbackLabel = toFallbackLabel(trace.fallbackReason);
  const hasTrace = Boolean(
    trace.workflowEngine ||
      workflowPath.length > 0 ||
      trace.fallbackReason ||
      trace.errorCode ||
      trace.toolName ||
      trace.requestId ||
      trace.executionId
  );
  const canOperateCheckpoint = Boolean(checkpointGraphName && checkpointThreadId && !isStreaming);
  const checkpointLabel = useMemo(() => {
    if (!checkpointThreadId) {
      return undefined;
    }
    return checkpointThreadId.length > 32 ? `${checkpointThreadId.slice(0, 16)}...${checkpointThreadId.slice(-8)}` : checkpointThreadId;
  }, [checkpointThreadId]);

  if (!hasTrace && steps.length === 0 && status === 'idle') {
    return null;
  }

  const timelineItems = [
    ...(steps.length > 0
      ? steps.map((step) => {
          const startedAt = formatTimestamp(step.startedAt ?? step.timestamp);
          const endedAt = formatTimestamp(step.endedAt);
          const isActiveStep = step.status === 'in_progress';
          const isFailedStep = step.status === 'failed';
          const color = isFailedStep ? 'red' as const : isActiveStep ? 'blue' as const : 'green' as const;
          const dot = isFailedStep
            ? <ExclamationCircleOutlined />
            : isActiveStep
              ? <LoadingOutlined spin />
              : step.kind === 'tool'
                ? <ToolOutlined />
                : step.kind === 'stage'
                  ? <ApartmentOutlined />
                  : <CheckCircleOutlined />;

          return {
            color,
            dot,
            children: (
              <Space direction="vertical" size={2}>
                <Typography.Text strong>{step.step}</Typography.Text>
                <Typography.Text style={{ whiteSpace: 'pre-wrap' }}>{step.description}</Typography.Text>
                <Typography.Text type="secondary">
                  {isFailedStep
                    ? `执行失败${endedAt ? ` · ${endedAt}` : ''}`
                    : isActiveStep
                      ? `执行中${startedAt ? ` · ${startedAt}` : ''}`
                      : `已完成${endedAt ? ` · ${endedAt}` : startedAt ? ` · ${startedAt}` : ''}`}
                </Typography.Text>
              </Space>
            ),
          };
        })
      : workflowPath.map((stage, index) => ({
          color: 'green' as const,
          dot: <ApartmentOutlined />,
          children: (
            <Space direction="vertical" size={2}>
              <Typography.Text strong>{`阶段 ${index + 1} · ${toStageLabel(stage)}`}</Typography.Text>
              <Typography.Text type="secondary">{toStageDescription(stage)}</Typography.Text>
              <Typography.Text type="secondary">规划阶段</Typography.Text>
            </Space>
          ),
        }))),
  ];

  const handleViewState = async () => {
    if (!checkpointGraphName || !checkpointThreadId) {
      return;
    }
    setCheckpointLoading('state');
    try {
      const state: CheckpointState = await taskRuntimeService.getCheckpointState(checkpointGraphName, checkpointThreadId);
      await modalApi.info({
        title: 'Checkpoint 当前状态',
        width: 840,
        content: renderJsonContent(state),
      });
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '获取 checkpoint 状态失败');
    } finally {
      setCheckpointLoading(null);
    }
  };

  const handleViewHistory = async () => {
    if (!checkpointGraphName || !checkpointThreadId) {
      return;
    }
    setCheckpointLoading('history');
    try {
      const history: CheckpointHistory = await taskRuntimeService.getCheckpointHistory(checkpointGraphName, checkpointThreadId, 20);
      await modalApi.info({
        title: 'Checkpoint 历史',
        width: 900,
        content: renderJsonContent(history),
      });
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '获取 checkpoint 历史失败');
    } finally {
      setCheckpointLoading(null);
    }
  };

  const handleResume = async () => {
    if (!checkpointGraphName || !checkpointThreadId || !onResumeCheckpoint) {
      return;
    }
    setCheckpointLoading('resume');
    try {
      await onResumeCheckpoint(checkpointGraphName, checkpointThreadId);
      messageApi.success('已发起 checkpoint 恢复执行');
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '恢复 checkpoint 失败');
    } finally {
      setCheckpointLoading(null);
    }
  };

  const handleClear = async () => {
    if (!checkpointGraphName || !checkpointThreadId) {
      return;
    }
    const confirmed = await modalApi.confirm({
      title: '清理 checkpoint',
      content: `确定删除 ${checkpointGraphName} / ${checkpointThreadId} 的 checkpoint 吗？`,
      okText: '删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
    });
    if (!confirmed) {
      return;
    }

    setCheckpointLoading('clear');
    try {
      const cleared = await taskRuntimeService.clearCheckpoint(checkpointGraphName, checkpointThreadId);
      if (cleared) {
        messageApi.success('checkpoint 已清理');
      } else {
        messageApi.warning('未找到可清理的 checkpoint');
      }
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '清理 checkpoint 失败');
    } finally {
      setCheckpointLoading(null);
    }
  };

  return (
    <>
      {contextHolder}
      {messageContextHolder}
      <Card
        size="small"
        title={
          <span>
            {isStreaming ? (
              <LoadingOutlined spin style={{ marginRight: 8 }} />
            ) : (
              <CheckCircleOutlined style={{ marginRight: 8, color: '#52c41a' }} />
            )}
            {'执行时间线'}
          </span>
        }
        style={{ marginTop: 16 }}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space size={[8, 8]} wrap>
            {trace.workflowEngine ? (
              <Tag icon={<ApartmentOutlined />} color="processing">
                {'规划引擎：'}{toEngineLabel(trace.workflowEngine)}
              </Tag>
            ) : null}
            {workflowPath.length > 0 ? (
              <Tag icon={<CheckCircleOutlined />} color="success">
                {'工作流阶段：'}{workflowPath.length}
              </Tag>
            ) : null}
            {steps.length > 0 ? <Tag color="blue">{'思考步骤：'}{steps.length}</Tag> : null}
            {status !== 'idle' ? <Tag color={STATUS_COLORS[status]}>{'状态：'}{STATUS_LABELS[status]}</Tag> : null}
            {trace.toolName ? (
              <Tag icon={<ToolOutlined />} color="gold">
                {'工具：'}{trace.toolName}
              </Tag>
            ) : null}
            {trace.errorCode ? <Tag color="error">{'错误码：'}{trace.errorCode}</Tag> : null}
            {trace.executionId ? <Tag color="purple">Execution: {trace.executionId}</Tag> : null}
            {trace.requestId ? <Tag color="default">Request: {trace.requestId}</Tag> : null}
            {checkpointLabel ? <Tag color="cyan">Checkpoint: {checkpointLabel}</Tag> : null}
          </Space>

          {canOperateCheckpoint ? (
            <Space size={[8, 8]} wrap>
              <Button icon={<EyeOutlined />} loading={checkpointLoading === 'state'} onClick={handleViewState}>
                查看状态
              </Button>
              <Button icon={<HistoryOutlined />} loading={checkpointLoading === 'history'} onClick={handleViewHistory}>
                查看历史
              </Button>
              <Button icon={<PlayCircleOutlined />} type="primary" loading={checkpointLoading === 'resume'} onClick={handleResume}>
                恢复执行
              </Button>
              <Button danger icon={<ClearOutlined />} loading={checkpointLoading === 'clear'} onClick={handleClear}>
                清理
              </Button>
            </Space>
          ) : null}

          {timelineItems.length > 0 ? <Timeline items={timelineItems} style={{ paddingTop: 4 }} /> : null}

          {fallbackLabel ? (
            <Alert
              type="warning"
              showIcon
              icon={<ExclamationCircleOutlined />}
              message={'本次执行发生了流程降级'}
              description={fallbackLabel}
            />
          ) : null}
        </Space>
      </Card>
    </>
  );
};
