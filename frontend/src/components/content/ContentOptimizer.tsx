/**
 * 内容优化器组件
 * 提供文本润色、改写、扩写、缩写、风格转换、语法纠错、SEO优化等功能
 */

import React, { useState } from 'react';
import { Form, Input, Select, Button, Card, message, Spin, InputNumber } from 'antd';
import { EditOutlined } from '@ant-design/icons';
import {
  optimizeContent,
  OPTIMIZATION_TYPES,
  CONTENT_STYLES,
  type ContentOptimizeResult,
} from '@/services/contentService';
import './ContentOptimizer.css';

const { TextArea } = Input;
const { Option } = Select;

export const ContentOptimizer: React.FC = () => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ContentOptimizeResult | null>(null);
  const [selectedAction, setSelectedAction] = useState<string>('polish');

  const handleOptimize = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      setResult(null);

      const response = await optimizeContent({
        action: selectedAction,
        ...values
      });

      if (response.success) {
        setResult(response.data ?? null);
        message.success('优化成功！');
      } else {
        message.error(response.error || '优化失败');
      }
    } catch (error: any) {
      if (error.errorFields) {
        message.error('请填写必填字段');
      } else {
        message.error('优化失败，请稍后重试');
        console.error('优化失败:', error);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    form.resetFields();
    setResult(null);
  };

  const handleCopyResult = () => {
    if (result && result.optimizedContent) {
      navigator.clipboard.writeText(result.optimizedContent);
      message.success('已复制到剪贴板');
    }
  };

  const needsTargetStyle = () => {
    return selectedAction === 'style_transfer';
  };

  const needsTargetLength = () => {
    return selectedAction === 'expand' || selectedAction === 'summarize';
  };

  const needsKeywords = () => {
    return selectedAction === 'seo_optimize';
  };

  const renderResult = () => {
    if (!result) return null;

    return (
      <Card
        title="优化结果"
        className="result-card"
        extra={
          <Button onClick={handleCopyResult} size="small">
            复制结果
          </Button>
        }
      >
        {result.optimizedContent && (
          <div className="result-section">
            <h4>优化后的内容：</h4>
            <div className="result-content">
              {result.optimizedContent}
            </div>
          </div>
        )}

        {result.checkResult && (
          <div className="result-section">
            <h4>检查结果：</h4>
            <pre className="result-content">
              {result.checkResult}
            </pre>
          </div>
        )}

        {result.originalLength && result.optimizedLength && (
          <div className="result-meta">
            <span>原文字数: {result.originalLength}</span>
            <span>优化后字数: {result.optimizedLength}</span>
            {result.compressionRatio && (
              <span>压缩率: {result.compressionRatio}</span>
            )}
          </div>
        )}
      </Card>
    );
  };

  return (
    <div className="content-optimizer">
      <Card className="form-card">
        <Spin spinning={loading} tip="正在优化中，请稍候...">
          <Form form={form} layout="vertical">
            <Form.Item
              label="优化类型"
              name="action"
              rules={[{ required: true, message: '请选择优化类型' }]}
              initialValue="polish"
            >
              <Select
                placeholder="请选择优化类型"
                onChange={setSelectedAction}
              >
                {Object.entries(OPTIMIZATION_TYPES).map(([key, value]) => (
                  <Option key={key} value={key}>{value}</Option>
                ))}
              </Select>
            </Form.Item>

            <Form.Item
              label="原始内容"
              name="content"
              rules={[{ required: true, message: '请输入要优化的内容' }]}
            >
              <TextArea
                rows={10}
                placeholder="请输入要优化的内容"
                showCount
              />
            </Form.Item>

            {needsTargetStyle() && (
              <Form.Item
                label="目标风格"
                name="targetStyle"
                rules={[{ required: true, message: '请选择目标风格' }]}
              >
                <Select placeholder="请选择目标风格">
                  {Object.entries(CONTENT_STYLES).map(([key, value]) => (
                    <Option key={key} value={key}>{value}</Option>
                  ))}
                </Select>
              </Form.Item>
            )}

            {needsTargetLength() && (
              <Form.Item
                label="目标字数"
                name="targetLength"
                rules={[{ required: false }]}
              >
                <InputNumber
                  min={100}
                  max={10000}
                  style={{ width: '100%' }}
                  placeholder="请输入目标字数（可选）"
                />
              </Form.Item>
            )}

            {needsKeywords() && (
              <Form.Item
                label="关键词"
                name="keywords"
                rules={[{ required: false }]}
              >
                <Input placeholder="请输入关键词，用逗号分隔（可选）" />
              </Form.Item>
            )}

            <Form.Item
              label="特殊要求"
              name="requirements"
              rules={[{ required: false }]}
            >
              <TextArea
                rows={3}
                placeholder="请输入特殊要求或说明（可选）"
              />
            </Form.Item>

            <Form.Item>
              <Button
                type="primary"
                onClick={handleOptimize}
                loading={loading}
                size="large"
                block
                icon={<EditOutlined />}
              >
                开始优化
              </Button>
              <Button
                onClick={handleClear}
                size="large"
                block
                style={{ marginTop: 8 }}
              >
                清空
              </Button>
            </Form.Item>
          </Form>
        </Spin>
      </Card>

      {renderResult()}
    </div>
  );
};
