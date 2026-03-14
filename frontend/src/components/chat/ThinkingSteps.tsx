import { Card, Steps } from 'antd';
import { CheckCircleOutlined, LoadingOutlined } from '@ant-design/icons';
import { ThinkingStep } from '@/types';

interface ThinkingStepsProps {
  steps: ThinkingStep[];
  isStreaming?: boolean;
}

export const ThinkingSteps = ({ steps, isStreaming = false }: ThinkingStepsProps) => {
  if (steps.length === 0) return null;

  return (
    <Card
      title={
        <span>
          {isStreaming ? (
            <LoadingOutlined spin style={{ marginRight: 8 }} />
          ) : (
            <CheckCircleOutlined style={{ marginRight: 8, color: '#52c41a' }} />
          )}
          思考执行过程
        </span>
      }
      size="small"
      style={{ marginTop: 16 }}
    >
      <Steps
        direction="vertical"
        size="small"
        current={isStreaming ? steps.length - 1 : steps.length}
        items={steps.map((step, index) => ({
          key: step.timestamp || `step-${index}`,
          title: step.step,
          description: <div style={{ whiteSpace: 'pre-wrap' }}>{step.description}</div>,
        }))}
      />
    </Card>
  );
};
