import { useMemo } from 'react';
import { Alert, Button, Card, Descriptions, List, Space, Tag, Typography } from 'antd';

import type {
  TaskRuntimeArtifact,
  TaskRuntimeEvaluationReport,
  TaskRuntimeGoal,
  TaskRuntimePlan,
  TaskRuntimeStatus,
} from '@/types';

interface TaskRuntimePlanCardProps {
  goal?: TaskRuntimeGoal | null;
  plan?: TaskRuntimePlan | null;
  taskStatus?: TaskRuntimeStatus | null;
  actionLoading?: 'pause' | 'resume' | 'cancel' | 'retry' | null;
  onPause?: () => void;
  onResume?: () => void;
  onCancel?: () => void;
  onRetry?: () => void;
}

const TASK_STATUS_LABELS: Record<string, string> = {
  pending: '待执行',
  running: '执行中',
  paused: '已暂停',
  succeeded: '已成功',
  failed: '已失败',
  cancelled: '已取消',
  timed_out: '已超时',
};

const TASK_STATUS_COLORS: Record<string, string> = {
  pending: 'default',
  running: 'processing',
  paused: 'warning',
  succeeded: 'success',
  failed: 'error',
  cancelled: 'default',
  timed_out: 'error',
};

/**
 * 把任务状态枚举映射为稳定文案，避免在 UI 层散落条件分支。
 */
const getTaskStatusLabel = (status?: string): string => {
  if (!status) {
    return '未知';
  }
  return TASK_STATUS_LABELS[status] ?? status;
};

/**
 * 统一产物内容预览，确保对象和长文本都能在卡片中简洁展示。
 */
const formatArtifactPreview = (artifact: TaskRuntimeArtifact): string => {
  if (typeof artifact.content === 'string') {
    return artifact.content.length > 160 ? `${artifact.content.slice(0, 160)}...` : artifact.content;
  }

  if (artifact.content === null || artifact.content === undefined) {
    return '暂无内容预览';
  }

  try {
    const serializedContent = JSON.stringify(artifact.content, null, 2);
    return serializedContent.length > 160 ? `${serializedContent.slice(0, 160)}...` : serializedContent;
  } catch {
    return '产物内容暂不支持预览';
  }
};

/**
 * 统一渲染验收报告列表，避免每个区域重复判断空数组。
 */
const renderReportTagGroup = (items: string[], color: string) => {
  if (items.length === 0) {
    return <Typography.Text type="secondary">暂无</Typography.Text>;
  }

  return (
    <Space size={[6, 6]} wrap>
      {items.map((item) => (
        <Tag key={item} color={color}>{item}</Tag>
      ))}
    </Space>
  );
};

const buildActionConfig = (status?: string) => {
  if (status === 'pending' || status === 'running') {
    return ['pause', 'cancel'] as Array<'pause' | 'resume' | 'cancel' | 'retry'>;
  }
  if (status === 'paused') {
    return ['resume', 'cancel'] as Array<'pause' | 'resume' | 'cancel' | 'retry'>;
  }
  if (status === 'failed' || status === 'cancelled' || status === 'timed_out') {
    return ['retry'] as Array<'pause' | 'resume' | 'cancel' | 'retry'>;
  }
  return [] as Array<'pause' | 'resume' | 'cancel' | 'retry'>;
};

const ActionButtons = ({
  status,
  actionLoading,
  onPause,
  onResume,
  onCancel,
  onRetry,
}: {
  status?: string;
  actionLoading?: 'pause' | 'resume' | 'cancel' | 'retry' | null;
  onPause?: () => void;
  onResume?: () => void;
  onCancel?: () => void;
  onRetry?: () => void;
}) => {
  const actions = buildActionConfig(status);
  const canPause = actions.includes('pause');
  const canResume = actions.includes('resume');
  const canCancel = actions.includes('cancel');
  const canRetry = actions.includes('retry');

  if (!canPause && !canResume && !canCancel && !canRetry) {
    return null;
  }

  return (
    <Space size={[8, 8]} wrap>
      {canPause ? (
        <Button loading={actionLoading === 'pause'} onClick={onPause}>
          暂停任务
        </Button>
      ) : null}
      {canResume ? (
        <Button type="primary" loading={actionLoading === 'resume'} onClick={onResume}>
          恢复任务
        </Button>
      ) : null}
      {canCancel ? (
        <Button danger loading={actionLoading === 'cancel'} onClick={onCancel}>
          取消任务
        </Button>
      ) : null}
      {canRetry ? (
        <Button type="primary" loading={actionLoading === 'retry'} onClick={onRetry}>
          重试任务
        </Button>
      ) : null}
    </Space>
  );
};

const EvaluationReportSection = ({ report }: { report: TaskRuntimeEvaluationReport }) => (
  <Space direction="vertical" size={8} style={{ width: '100%' }}>
    <Space size={[8, 8]} wrap>
      <Typography.Text strong>最终验收报告</Typography.Text>
      <Tag color={report.success ? 'success' : 'error'}>{report.success ? '已通过' : '未通过'}</Tag>
      <Tag color="purple">评分：{report.overallScore}</Tag>
    </Space>
    {report.summary ? <Alert type={report.success ? 'success' : 'warning'} showIcon message={report.summary} /> : null}
    <Descriptions size="small" column={1} bordered>
      <Descriptions.Item label="满足标准">
        {renderReportTagGroup(report.satisfiedCriteria, 'success')}
      </Descriptions.Item>
      <Descriptions.Item label="缺失项">
        {renderReportTagGroup(report.missingCriteria, 'error')}
      </Descriptions.Item>
      <Descriptions.Item label="风险">
        {renderReportTagGroup(report.risks, 'orange')}
      </Descriptions.Item>
      <Descriptions.Item label="建议">
        {renderReportTagGroup(report.recommendations, 'blue')}
      </Descriptions.Item>
    </Descriptions>
  </Space>
);

export const TaskRuntimePlanCard = ({
  goal,
  plan,
  taskStatus,
  actionLoading,
  onPause,
  onResume,
  onCancel,
  onRetry,
}: TaskRuntimePlanCardProps) => {
  const artifacts = useMemo(() => taskStatus?.artifacts ?? [], [taskStatus?.artifacts]);

  if (!goal && !plan && !taskStatus) {
    return null;
  }

  const statusColor = TASK_STATUS_COLORS[taskStatus?.status ?? 'pending'] ?? 'default';

  return (
    <Card size="small" title="任务目标与计划" style={{ marginTop: 16 }}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {taskStatus ? (
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            <Space size={[8, 8]} wrap>
              <Typography.Text strong>任务状态</Typography.Text>
              <Tag color={statusColor}>{getTaskStatusLabel(taskStatus.status)}</Tag>
              {taskStatus.taskId ? <Tag color="cyan">Task: {taskStatus.taskId}</Tag> : null}
              {taskStatus.executionId ? <Tag color="purple">Execution: {taskStatus.executionId}</Tag> : null}
              {taskStatus.currentStepId ? <Tag color="gold">当前步骤: {taskStatus.currentStepId}</Tag> : null}
            </Space>
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="请求 ID">{taskStatus.requestId || '-'}</Descriptions.Item>
              <Descriptions.Item label="当前计划">{taskStatus.currentPlanId || '-'}</Descriptions.Item>
              <Descriptions.Item label="最新检查点">{taskStatus.latestCheckpoint?.checkpointId || taskStatus.checkpointId || '-'}</Descriptions.Item>
              <Descriptions.Item label="检查点原因">
                {taskStatus.latestCheckpoint?.checkpointReason || '-'}
              </Descriptions.Item>
            </Descriptions>
            <ActionButtons
              status={taskStatus.status}
              actionLoading={actionLoading}
              onPause={onPause}
              onResume={onResume}
              onCancel={onCancel}
              onRetry={onRetry}
            />
            {taskStatus.termination?.finalOutput ? (
              <Alert
                type={taskStatus.status === 'succeeded' ? 'success' : 'info'}
                showIcon
                message="最终答案"
                description={taskStatus.termination.finalOutput}
              />
            ) : null}
          </Space>
        ) : null}

        {goal ? (
          <Space direction="vertical" size={6} style={{ width: '100%' }}>
            <Typography.Text strong>目标</Typography.Text>
            <Typography.Text>{goal.normalizedGoal}</Typography.Text>
            {goal.successCriteria.length > 0 ? (
              <Space size={[6, 6]} wrap>
                {goal.successCriteria.map((criterion) => (
                  <Tag key={criterion} color="blue">{criterion}</Tag>
                ))}
              </Space>
            ) : null}
          </Space>
        ) : null}

        {plan ? (
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Space size={[8, 8]} wrap>
              <Typography.Text strong>执行计划</Typography.Text>
              <Tag color="processing">Plan: {plan.planId}</Tag>
              <Tag color="purple">Version: {plan.version}</Tag>
              <Tag color="success">Steps: {plan.steps.length}</Tag>
            </Space>
            {plan.reasoning ? <Typography.Text type="secondary">{plan.reasoning}</Typography.Text> : null}
            <List
              size="small"
              dataSource={plan.steps}
              renderItem={(step, index) => (
                <List.Item>
                  <Space direction="vertical" size={2} style={{ width: '100%' }}>
                    <Typography.Text strong>{index + 1}. {step.title}</Typography.Text>
                    {step.description ? <Typography.Text>{step.description}</Typography.Text> : null}
                    <Space size={[6, 6]} wrap>
                      <Tag>{step.stepType}</Tag>
                      {step.dependsOn.length > 0 ? <Tag color="default">依赖: {step.dependsOn.join(', ')}</Tag> : null}
                    </Space>
                  </Space>
                </List.Item>
              )}
            />
          </Space>
        ) : null}

        {taskStatus?.latestCheckpoint ? (
          <Space direction="vertical" size={6} style={{ width: '100%' }}>
            <Typography.Text strong>检查点</Typography.Text>
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="检查点 ID">
                {taskStatus.latestCheckpoint.checkpointId}
              </Descriptions.Item>
              <Descriptions.Item label="已完成步骤">
                {taskStatus.latestCheckpoint.completedStepIds.length > 0
                  ? taskStatus.latestCheckpoint.completedStepIds.join(', ')
                  : '暂无'}
              </Descriptions.Item>
              <Descriptions.Item label="迭代次数">
                {taskStatus.latestCheckpoint.iterationCount}
              </Descriptions.Item>
            </Descriptions>
          </Space>
        ) : null}

        {taskStatus?.evaluationReport ? (
          <EvaluationReportSection report={taskStatus.evaluationReport} />
        ) : null}

        {artifacts.length > 0 ? (
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Typography.Text strong>任务产物</Typography.Text>
            <List
              size="small"
              dataSource={artifacts}
              renderItem={(artifact) => (
                <List.Item>
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    <Space size={[6, 6]} wrap>
                      <Typography.Text strong>{artifact.title || artifact.artifactType}</Typography.Text>
                      <Tag color="blue">{artifact.artifactType}</Tag>
                      {artifact.sourceStepId ? <Tag color="default">来源步骤: {artifact.sourceStepId}</Tag> : null}
                    </Space>
                    <Typography.Paragraph style={{ marginBottom: 0 }} ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}>
                      {formatArtifactPreview(artifact)}
                    </Typography.Paragraph>
                  </Space>
                </List.Item>
              )}
            />
          </Space>
        ) : null}
      </Space>
    </Card>
  );
};
