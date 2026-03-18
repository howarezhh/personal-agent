import {
  Alert,
  Card,
  Space,
  Tag,
  Timeline,
  Typography,
} from 'antd';
import {
  ApartmentOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  InfoCircleOutlined,
  LoadingOutlined,
  ToolOutlined,
} from '@ant-design/icons';

import type { StreamStatus, ThinkingStep, WorkflowTrace } from '@/types';

interface ExecutionTimelinePanelProps {
  steps: ThinkingStep[];
  trace: WorkflowTrace;
  status?: StreamStatus;
  isStreaming?: boolean;
}

const STATUS_LABELS: Record<StreamStatus, string> = {
  idle: '空闲',
  connecting: '连接中',
  streaming: '生成中',
  completed: '已完成',
  error: '失败',
  cancelled: '已取消',
};

const STATUS_COLORS: Record<StreamStatus, string> = {
  idle: 'default',
  connecting: 'processing',
  streaming: 'blue',
  completed: 'success',
  error: 'error',
  cancelled: 'warning',
};

const STAGE_LABELS: Record<string, string> = {
  intent_recognition: '\u610f\u56fe\u8bc6\u522b',
  retrieval: '\u77e5\u8bc6\u68c0\u7d22',
  tool_call: '\u5de5\u5177\u8c03\u7528',
  generation: '\u7b54\u6848\u751f\u6210',
  multi_agent: '\u591a Agent \u534f\u4f5c',
};

const STAGE_DESCRIPTIONS: Record<string, string> = {
  intent_recognition: '\u5206\u6790\u7528\u6237\u95ee\u9898\uff0c\u5e76\u51b3\u5b9a\u672c\u6b21\u8bf7\u6c42\u7684\u4e3b\u6267\u884c\u5206\u652f\u3002',
  retrieval: '\u4ece\u77e5\u8bc6\u5e93\u6216\u6587\u6863\u4e2d\u68c0\u7d22\u4e0a\u4e0b\u6587\uff0c\u51c6\u5907\u56de\u7b54\u6240\u9700\u4fe1\u606f\u3002',
  tool_call: '\u8c03\u7528\u5916\u90e8\u5de5\u5177\u6216\u670d\u52a1\uff0c\u8865\u5145\u56de\u7b54\u6240\u9700\u6570\u636e\u3002',
  generation: '\u7efc\u5408\u4e0a\u4e0b\u6587\u4e0e\u5de5\u5177\u7ed3\u679c\uff0c\u751f\u6210\u6700\u7ec8\u7b54\u6848\u3002',
  multi_agent: '\u6309\u591a Agent \u7f16\u6392\u6d41\u7a0b\u6267\u884c\u590d\u6742\u4efb\u52a1\u3002',
};

const FALLBACK_REASON_LABELS: Record<string, string> = {
  unknown_router_action: '\u8def\u7531\u8fd4\u56de\u4e86\u672a\u77e5\u52a8\u4f5c\uff0c\u5df2\u56de\u9000\u5230\u5b89\u5168\u5206\u652f\u3002',
  knowledge_base_disabled: '\u77e5\u8bc6\u5e93\u5f00\u5173\u5173\u95ed\uff0c\u5df2\u56de\u9000\u5230\u76f4\u63a5\u56de\u7b54\u3002',
  retrieval_no_result: '\u672a\u68c0\u7d22\u5230\u6709\u6548\u7ed3\u679c\uff0c\u5df2\u56de\u9000\u5230\u901a\u7528\u56de\u7b54\u3002',
  tool_route_to_retrieval: '\u65e0\u9700\u8c03\u7528\u5de5\u5177\uff0c\u5df2\u5207\u6362\u5230\u68c0\u7d22\u6d41\u7a0b\u3002',
  tool_not_needed: '\u65e0\u9700\u8c03\u7528\u5de5\u5177\uff0c\u5df2\u76f4\u63a5\u751f\u6210\u56de\u7b54\u3002',
  tool_failure: '\u5de5\u5177\u8c03\u7528\u5931\u8d25\uff0c\u5df2\u56de\u9000\u5230\u901a\u7528\u56de\u7b54\u3002',
  tool_error_fallback: '\u5de5\u5177\u6267\u884c\u5f02\u5e38\uff0c\u5df2\u56de\u9000\u5230\u901a\u7528\u56de\u7b54\u3002',
  tool_result_missing: '\u5de5\u5177\u672a\u8fd4\u56de\u7ed3\u679c\uff0c\u5df2\u56de\u9000\u5230\u901a\u7528\u56de\u7b54\u3002',
  workflow_policy_sanitized: '\u5de5\u4f5c\u6d41\u5df2\u6309\u8fd0\u884c\u65f6\u7b56\u7565\u81ea\u52a8\u6536\u655b\u3002',
  workflow_policy_fallback: '\u5de5\u4f5c\u6d41\u914d\u7f6e\u65e0\u6548\uff0c\u5df2\u56de\u9000\u5230\u5b89\u5168\u9ed8\u8ba4\u914d\u7f6e\u3002',
  default_workflow_config: '\u672a\u63d0\u4f9b\u6709\u6548\u5de5\u4f5c\u6d41\u914d\u7f6e\uff0c\u5df2\u4f7f\u7528\u9ed8\u8ba4\u914d\u7f6e\u3002',
};

const ENGINE_LABELS: Record<string, string> = {
  builtin: '\u5185\u7f6e\u89c4\u5212\u5668',
  langgraph: 'LangGraph',
};

const toStageLabel = (stage: string): string => STAGE_LABELS[stage] ?? stage;

const toStageDescription = (stage: string): string =>
  STAGE_DESCRIPTIONS[stage] ?? '\u6267\u884c\u8be5\u9636\u6bb5\u5bf9\u5e94\u7684\u5de5\u4f5c\u6d41\u6b65\u9aa4\u3002';

const toEngineLabel = (workflowEngine?: string): string | undefined => {
  if (!workflowEngine) {
    return undefined;
  }

  return ENGINE_LABELS[workflowEngine] ?? workflowEngine;
};

const toFallbackLabel = (fallbackReason?: string): string | undefined => {
  if (!fallbackReason) {
    return undefined;
  }

  return FALLBACK_REASON_LABELS[fallbackReason] ?? fallbackReason;
};

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

export const ExecutionTimelinePanel = ({
  steps,
  trace,
  status = 'idle',
  isStreaming = false,
}: ExecutionTimelinePanelProps) => {
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

  if (!hasTrace && steps.length === 0 && status === 'idle') {
    return null;
  }

  const timelineItems = [
    ...workflowPath.map((stage, index) => ({
      color: 'green' as const,
      dot: <ApartmentOutlined />,
      children: (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>{`\u9636\u6bb5 ${index + 1} \u00b7 ${toStageLabel(stage)}`}</Typography.Text>
          <Typography.Text type="secondary">{toStageDescription(stage)}</Typography.Text>
          <Typography.Text type="secondary">\u89c4\u5212\u9636\u6bb5</Typography.Text>
        </Space>
      ),
    })),
    ...steps.map((step, index) => {
      const stepTime = formatTimestamp(step.timestamp);
      const isActiveStep = isStreaming && index === steps.length - 1;

      return {
        color: isActiveStep ? ('blue' as const) : ('gray' as const),
        dot: isActiveStep ? <LoadingOutlined spin /> : <InfoCircleOutlined />,
        children: (
          <Space direction="vertical" size={2}>
            <Typography.Text strong>{step.step}</Typography.Text>
            <Typography.Text style={{ whiteSpace: 'pre-wrap' }}>{step.description}</Typography.Text>
            <Typography.Text type="secondary">
              {stepTime ? `\u6267\u884c\u8fc7\u7a0b \u00b7 ${stepTime}` : '\u6267\u884c\u8fc7\u7a0b'}
            </Typography.Text>
          </Space>
        ),
      };
    }),
  ];

  return (
    <Card
      size="small"
      title={
        <span>
          {isStreaming ? (
            <LoadingOutlined spin style={{ marginRight: 8 }} />
          ) : (
            <CheckCircleOutlined style={{ marginRight: 8, color: '#52c41a' }} />
          )}
          {'\u6267\u884c\u65f6\u95f4\u7ebf'}
        </span>
      }
      style={{ marginTop: 16 }}
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Space size={[8, 8]} wrap>
          {trace.workflowEngine ? (
            <Tag icon={<ApartmentOutlined />} color="processing">
              {'\u89c4\u5212\u5f15\u64ce\uff1a'}{toEngineLabel(trace.workflowEngine)}
            </Tag>
          ) : null}
          {workflowPath.length > 0 ? (
            <Tag icon={<CheckCircleOutlined />} color="success">
              {'\u5de5\u4f5c\u6d41\u9636\u6bb5\uff1a'}{workflowPath.length}
            </Tag>
          ) : null}
          {steps.length > 0 ? <Tag color="blue">{'\u601d\u8003\u6b65\u9aa4\uff1a'}{steps.length}</Tag> : null}
          {status !== 'idle' ? <Tag color={STATUS_COLORS[status]}>{'状态：'}{STATUS_LABELS[status]}</Tag> : null}
          {trace.toolName ? (
            <Tag icon={<ToolOutlined />} color="gold">
              {'\u5de5\u5177\uff1a'}{trace.toolName}
            </Tag>
          ) : null}
          {trace.errorCode ? <Tag color="error">{'\u9519\u8bef\u7801\uff1a'}{trace.errorCode}</Tag> : null}
          {trace.executionId ? <Tag color="purple">Execution: {trace.executionId}</Tag> : null}
          {trace.requestId ? <Tag color="default">Request: {trace.requestId}</Tag> : null}
        </Space>

        {timelineItems.length > 0 ? <Timeline items={timelineItems} style={{ paddingTop: 4 }} /> : null}

        {fallbackLabel ? (
          <Alert
            type="warning"
            showIcon
            icon={<ExclamationCircleOutlined />}
            message={'\u672c\u6b21\u6267\u884c\u53d1\u751f\u4e86\u6d41\u7a0b\u964d\u7ea7'}
            description={fallbackLabel}
          />
        ) : null}
      </Space>
    </Card>
  );
};
