import React from 'react';
import { Alert, Card, Descriptions, Empty, List, Space, Tag, Typography } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';

import type { ToolExecuteResponse } from '@/services/toolService';

const { Paragraph, Text } = Typography;

type ToolExecutionResultProps = {
  result: ToolExecuteResponse;
};

const isPlainObject = (value: unknown): value is Record<string, unknown> => {
  return Object.prototype.toString.call(value) === '[object Object]';
};

const formatFieldLabel = (fieldName: string): string => {
  return fieldName
    .replace(/_/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/\b\w/g, (character) => character.toUpperCase());
};

const renderPrimitiveValue = (value: string | number | boolean) => {
  if (typeof value === 'boolean') {
    return <Tag color={value ? 'success' : 'default'}>{value ? '是' : '否'}</Tag>;
  }

  if (typeof value === 'number') {
    return <Text>{value}</Text>;
  }

  return (
    <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
      {value || '-'}
    </Paragraph>
  );
};

const renderStructuredValue = (value: unknown, path: string): React.ReactNode => {
  if (value === null || value === undefined) {
    return <Text type="secondary">暂无内容</Text>;
  }

  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return renderPrimitiveValue(value);
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无列表数据" />;
    }

    return (
      <List
        size="small"
        bordered
        dataSource={value}
        renderItem={(item, index) => (
          <List.Item key={`${path}-${index}`}>
            <div style={{ width: '100%' }}>
              <Text strong style={{ display: 'block', marginBottom: 8 }}>
                第 {index + 1} 项
              </Text>
              {renderStructuredValue(item, `${path}-${index}`)}
            </div>
          </List.Item>
        )}
      />
    );
  }

  if (isPlainObject(value)) {
    const entries = Object.entries(value);

    if (entries.length === 0) {
      return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无对象数据" />;
    }

    return (
      <Descriptions bordered column={1} size="small">
        {entries.map(([fieldName, fieldValue]) => (
          <Descriptions.Item key={`${path}-${fieldName}`} label={formatFieldLabel(fieldName)}>
            {renderStructuredValue(fieldValue, `${path}-${fieldName}`)}
          </Descriptions.Item>
        ))}
      </Descriptions>
    );
  }

  return <Text>{String(value)}</Text>;
};

const ToolExecutionResult: React.FC<ToolExecutionResultProps> = ({ result }) => {
  const hasData = result.data !== null && result.data !== undefined;
  const hasMetadata = result.metadata !== null && result.metadata !== undefined;

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        showIcon
        type={result.success ? 'success' : 'error'}
        icon={result.success ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
        message={result.success ? '工具执行成功' : '工具执行失败'}
        description={result.success ? '结果已按结构化方式展示。' : (result.error || '未返回具体错误信息')}
      />

      {hasData && (
        <Card title="结果数据" size="small">
          {renderStructuredValue(result.data, 'result-data')}
        </Card>
      )}

      {hasMetadata && (
        <Card title={result.success ? '附加信息' : '错误上下文'} size="small">
          {renderStructuredValue(result.metadata, 'result-metadata')}
        </Card>
      )}

      {!hasData && !hasMetadata && (
        <Card size="small">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="工具未返回可展示内容" />
        </Card>
      )}
    </Space>
  );
};

export default ToolExecutionResult;
