import { useMemo, useState } from 'react';
import { Alert, Button, Card, Col, Form, Input, InputNumber, Row, Select, Space, Statistic, Typography, message } from 'antd';
import { EditOutlined } from '@ant-design/icons';

import { toContentOptimizeRequestContract } from '@/adapters/contentAdapter';
import { ContentResultPanel } from '@/components/content/ContentResultPanel';
import { API_PATHS } from '@/constants/api';
import { contentStyleOptions, optimizationActionMeta } from '@/constants/contentOptions';
import { useContentGenerationStream } from '@/hooks/useContentGenerationStream';

import './ContentOptimizer.css';

const { TextArea } = Input;
const { Paragraph, Text } = Typography;

type OptimizationActionKey =
  | 'polish'
  | 'rewrite'
  | 'expand'
  | 'summarize'
  | 'style_transfer'
  | 'grammar_check'
  | 'seo_optimize';

const optimizationOptions = Object.entries(optimizationActionMeta).map(([value, meta]) => ({
  value,
  label: meta.label,
}));

const needsTargetStyle = (action: OptimizationActionKey) => action === 'style_transfer';
const needsTargetLength = (action: OptimizationActionKey) => action === 'expand' || action === 'summarize';
const needsKeywords = (action: OptimizationActionKey) => action === 'seo_optimize';

export const ContentOptimizer = () => {
  const [form] = Form.useForm();
  const [selectedAction, setSelectedAction] = useState<OptimizationActionKey>('polish');
  const { cancel, errorMessage, generationId, isStreaming, reset, result, runStream, streamingText } =
    useContentGenerationStream<Record<string, unknown>>();

  const currentContent = Form.useWatch('content', form) as string | undefined;
  const actionMeta = useMemo(() => optimizationActionMeta[selectedAction], [selectedAction]);

  const handleActionChange = (action: OptimizationActionKey) => {
    const currentValues = form.getFieldsValue();
    setSelectedAction(action);
    reset();
    form.setFieldsValue({
      action,
      content: currentValues.content,
      requirements: currentValues.requirements,
      targetStyle: undefined,
      targetLength: undefined,
      keywords: undefined,
    });
  };

  const handleOptimize = async () => {
    try {
      const values = (await form.validateFields()) as Record<string, unknown>;
      const response = await runStream(
        API_PATHS.content.optimize,
        toContentOptimizeRequestContract({
          action: selectedAction,
          content: String(values.content ?? ''),
          targetStyle: values.targetStyle ? String(values.targetStyle) : undefined,
          targetLength: typeof values.targetLength === 'number' ? values.targetLength : undefined,
          keywords: values.keywords ? String(values.keywords) : undefined,
          requirements: values.requirements ? String(values.requirements) : undefined,
        })
      );

      if (response.success) {
        message.open({ key: 'content-optimize', type: 'success', content: `${actionMeta.label}完成` });
        return;
      }

      if (response.error === '已取消生成') {
        message.open({ key: 'content-optimize', type: 'warning', content: '已停止当前优化' });
        return;
      }

      message.open({ key: 'content-optimize', type: 'error', content: response.error || `${actionMeta.label}失败` });
    } catch (error: any) {
      if (error?.errorFields) {
        message.open({ key: 'content-optimize', type: 'warning', content: '请先补充必填信息' });
      } else {
        message.open({ key: 'content-optimize', type: 'error', content: `${actionMeta.label}失败，请稍后重试` });
        console.error('content optimize failed', error);
      }
    }
  };

  const handleStop = () => {
    cancel();
    message.open({ key: 'content-optimize', type: 'warning', content: '已停止当前优化' });
  };

  const handleReset = () => {
    form.resetFields();
    form.setFieldsValue({ action: selectedAction });
    reset();
  };

  return (
    <div className="content-optimizer">
      <Row gutter={[20, 20]}>
        <Col xs={24} xl={11}>
          <Card className="content-optimizer__form-card" title={actionMeta.label} bordered={false}>
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <Alert type="info" showIcon message={actionMeta.description} description={actionMeta.hint} />

              {errorMessage ? <Alert type="error" showIcon message={errorMessage} /> : null}

              <div className="content-optimizer__stats">
                <Card className="content-optimizer__stat-card" bordered={false}>
                  <Statistic title="当前字数" value={currentContent?.length ?? 0} />
                </Card>
                <Card className="content-optimizer__stat-card" bordered={false}>
                  <Statistic title="当前模式" value={actionMeta.label} />
                </Card>
              </div>

              <Paragraph className="content-optimizer__guide">
                <Text strong>填写建议：</Text>
                原文内容建议一次性粘贴完整，再切换优化模式尝试不同版本，便于横向比较。
              </Paragraph>

              <Form form={form} layout="vertical" initialValues={{ action: selectedAction }} className="content-optimizer__form">
                <Form.Item label="优化类型" name="action" rules={[{ required: true, message: '请选择优化类型' }]}>
                  <Select placeholder="选择优化类型" options={optimizationOptions} onChange={handleActionChange} />
                </Form.Item>

                <Form.Item label="原始内容" name="content" rules={[{ required: true, message: '请输入需要优化的内容' }]}>
                  <TextArea rows={14} placeholder="输入或粘贴需要优化的内容" showCount maxLength={12000} />
                </Form.Item>

                {needsTargetStyle(selectedAction) ? (
                  <Form.Item
                    label="目标风格"
                    name="targetStyle"
                    preserve={false}
                    rules={[{ required: true, message: '请选择目标风格' }]}
                  >
                    <Select placeholder="选择目标风格" options={contentStyleOptions} />
                  </Form.Item>
                ) : null}

                {needsTargetLength(selectedAction) ? (
                  <Form.Item label="目标字数" name="targetLength" preserve={false}>
                    <InputNumber min={100} max={10000} step={50} style={{ width: '100%' }} placeholder="例如：300" />
                  </Form.Item>
                ) : null}

                {needsKeywords(selectedAction) ? (
                  <Form.Item label="关键词" name="keywords" preserve={false}>
                    <Input placeholder="多个关键词用逗号分隔，例如：AI助手,企业知识库" />
                  </Form.Item>
                ) : null}

                <Form.Item label="补充要求" name="requirements">
                  <TextArea rows={4} placeholder="补充语气、目标场景、禁用词或格式要求" showCount maxLength={1200} />
                </Form.Item>

                <Form.Item className="content-optimizer__actions">
                  <Space size="middle" wrap>
                    <Button type="primary" icon={<EditOutlined />} size="large" loading={isStreaming} onClick={handleOptimize}>
                      开始优化
                    </Button>
                    <Button size="large" onClick={handleReset} disabled={isStreaming}>
                      清空结果
                    </Button>
                    {isStreaming ? (
                      <Button danger size="large" onClick={handleStop}>
                        停止优化
                      </Button>
                    ) : null}
                  </Space>
                </Form.Item>
              </Form>
            </Space>
          </Card>
        </Col>

        <Col xs={24} xl={13}>
          <ContentResultPanel
            title={`${actionMeta.label}结果`}
            result={result}
            generationId={generationId}
            isStreaming={isStreaming}
            streamingContent={streamingText}
            emptyDescription="提交优化请求后，这里会实时展示优化结果、长度变化和完整返回结构。"
          />
        </Col>
      </Row>
    </div>
  );
};
