import type { ReactNode } from 'react';
import { Button, Card, Collapse, Descriptions, Empty, Space, Tag, Typography, message } from 'antd';
import { CopyOutlined } from '@ant-design/icons';

import './ContentResultPanel.css';

const { Paragraph, Text } = Typography;

const FIELD_LABELS: Record<string, string> = {
  action: '操作',
  age: '年龄',
  abilities: '能力',
  ability: '能力',
  background: '背景',
  backstory: '背景故事',
  basicInfo: '基础信息',
  chapterPlan: '章节规划',
  chapterNumber: '章节编号',
  chapterTitle: '章节标题',
  compressionRatio: '压缩比例',
  coreConflict: '核心冲突',
  duration: '时长（分钟）',
  generationId: '生成记录',
  genre: '题材',
  goals: '目标',
  importantLocations: '重要地点',
  keywords: '关键词',
  mainCharacters: '主要角色',
  name: '名称',
  organizations: '组织势力',
  optimizedLength: '优化后长度',
  originalLength: '原文长度',
  personality: '性格',
  plotStages: '情节阶段',
  powerSystem: '力量体系',
  rawCharacter: '原始角色设定',
  rawOutline: '原始大纲',
  rawStoryboard: '原始分镜',
  rawWorldview: '原始世界观',
  relationships: '人物关系',
  rules: '特殊规则',
  sceneNumber: '场次编号',
  scriptType: '脚本类型',
  socialStructure: '社会结构',
  style: '风格',
  targetAudience: '目标受众',
  targetLength: '目标字数',
  targetStyle: '目标风格',
  title: '标题',
  uniqueSettings: '独特设定',
  weaknesses: '弱点',
  worldBackground: '世界背景',
  wordCount: '字数',
};

const STRUCTURED_FIELD_LABELS: Record<string, string> = {
  character: '角色设定',
  outline: '大纲结果',
  storyboard: '分镜结果',
  worldview: '世界观设定',
};

const TEXT_FIELD_LABELS: Record<string, string> = {
  checkResult: '检查结果',
  content: '正文内容',
  continuedContent: '续写内容',
  optimizedContent: '优化结果',
  originalContent: '原始内容',
};

interface ContentResultPanelProps {
  title: string;
  result: Record<string, unknown> | null;
  emptyDescription: string;
  generationId?: string | null;
  isStreaming?: boolean;
  streamingContent?: string;
}

const isScalarValue = (value: unknown): value is string | number | boolean =>
  ['string', 'number', 'boolean'].includes(typeof value);

const isNonEmptyScalar = (value: unknown): value is string | number | boolean => {
  if (!isScalarValue(value)) {
    return false;
  }

  return typeof value !== 'string' || value.trim().length > 0;
};

const humanizeFieldLabel = (key: string) => {
  if (FIELD_LABELS[key]) {
    return FIELD_LABELS[key];
  }

  const normalized = key
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .trim();

  if (!normalized) {
    return key;
  }

  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
};

const normalizeDisplayValue = (value: unknown): string | undefined => {
  if (typeof value === 'string') {
    return value.trim() || undefined;
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }

  if (Array.isArray(value)) {
    if (value.length === 0 || !value.every((item) => isNonEmptyScalar(item))) {
      return undefined;
    }

    return value.map((item) => String(item)).join('、');
  }

  if (value && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 1 && typeof entries[0][1] === 'string') {
      return entries[0][1] as string;
    }
  }

  return undefined;
};

const structuredValueToText = (value: unknown, indent = 0): string => {
  const prefix = '  '.repeat(indent);

  if (typeof value === 'string') {
    return value.trim();
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }

  if (Array.isArray(value)) {
    return value
      .map((item, index) => {
        const itemText = structuredValueToText(item, indent + 1);
        return itemText ? `${prefix}${index + 1}. ${itemText}` : '';
      })
      .filter(Boolean)
      .join('\n');
  }

  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, entryValue]) => {
        const entryText = structuredValueToText(entryValue, indent + 1);
        return entryText ? `${prefix}${humanizeFieldLabel(key)}：\n${entryText}` : '';
      })
      .filter(Boolean)
      .join('\n\n');
  }

  return '';
};

const renderStructuredValue = (value: unknown, path = 'root'): ReactNode => {
  if (!value && value !== 0 && value !== false) {
    return <Text type="secondary">暂无内容</Text>;
  }

  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return <Paragraph className="content-result-panel__text">{String(value)}</Paragraph>;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <Text type="secondary">暂无内容</Text>;
    }

    if (value.every((item) => isNonEmptyScalar(item))) {
      return (
        <div className="content-result-panel__tag-list">
          {value.map((item, index) => (
            <Tag key={`${path}-${index}`} className="content-result-panel__tag">
              {String(item)}
            </Tag>
          ))}
        </div>
      );
    }

    return (
      <div className="content-result-panel__nested-list">
        {value.map((item, index) => (
          <div key={`${path}-${index}`} className="content-result-panel__nested-card">
            <Text strong className="content-result-panel__nested-title">
              条目 {index + 1}
            </Text>
            {renderStructuredValue(item, `${path}-${index}`)}
          </div>
        ))}
      </div>
    );
  }

  const entries = Object.entries(value as Record<string, unknown>).filter(
    ([, entryValue]) => entryValue !== null && entryValue !== undefined && entryValue !== ''
  );

  if (entries.length === 0) {
    return <Text type="secondary">暂无内容</Text>;
  }

  const scalarEntries = entries
    .map(([key, entryValue]) => ({
      key,
      label: humanizeFieldLabel(key),
      text: normalizeDisplayValue(entryValue),
    }))
    .filter((entry): entry is { key: string; label: string; text: string } => Boolean(entry.text));

  const complexEntries = entries.filter(([, entryValue]) => normalizeDisplayValue(entryValue) === undefined);

  return (
    <div className="content-result-panel__structured-block">
      {scalarEntries.length > 0 ? (
        <div className="content-result-panel__kv-grid">
          {scalarEntries.map((entry) => (
            <div key={`${path}-${entry.key}`} className="content-result-panel__kv-card">
              <Text type="secondary" className="content-result-panel__kv-label">
                {entry.label}
              </Text>
              <div className="content-result-panel__kv-value">{entry.text}</div>
            </div>
          ))}
        </div>
      ) : null}

      {complexEntries.length > 0 ? (
        <div className="content-result-panel__nested-list">
          {complexEntries.map(([key, entryValue]) => (
            <div key={`${path}-${key}`} className="content-result-panel__nested-card">
              <Text strong className="content-result-panel__nested-title">
                {humanizeFieldLabel(key)}
              </Text>
              {renderStructuredValue(entryValue, `${path}-${key}`)}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
};

const copyText = async (text: string, successMessage: string) => {
  try {
    await navigator.clipboard.writeText(text);
    message.success(successMessage);
  } catch (error) {
    message.error('复制失败，请稍后重试');
    console.error('copy result failed', error);
  }
};

export const ContentResultPanel = ({
  title,
  result,
  emptyDescription,
  generationId,
  isStreaming = false,
  streamingContent,
}: ContentResultPanelProps) => {
  if (!result && !streamingContent) {
    return (
      <Card title={title} className="content-result-panel">
        <div className="content-result-panel__empty">
          <Empty description={emptyDescription} />
        </div>
      </Card>
    );
  }

  const safeResult = result ?? {};
  const rawJson = JSON.stringify(safeResult, null, 2);
  const resolvedGenerationId = generationId || normalizeDisplayValue(safeResult.generationId);
  const shouldShowStreaming = Boolean(streamingContent) && (isStreaming || !result);

  const primaryText =
    (shouldShowStreaming ? streamingContent : undefined) ||
    normalizeDisplayValue(safeResult.optimizedContent) ||
    normalizeDisplayValue(safeResult.content) ||
    normalizeDisplayValue(safeResult.continuedContent) ||
    normalizeDisplayValue(safeResult.checkResult) ||
    structuredValueToText(safeResult.outline) ||
    structuredValueToText(safeResult.character) ||
    structuredValueToText(safeResult.worldview) ||
    structuredValueToText(safeResult.storyboard) ||
    rawJson;

  const metaItems = Object.entries(safeResult).filter(([key, value]) => {
    if (['received'].includes(key)) {
      return false;
    }

    if (TEXT_FIELD_LABELS[key] || STRUCTURED_FIELD_LABELS[key]) {
      return false;
    }

    return isScalarValue(value);
  });

  const textSections = Object.entries(TEXT_FIELD_LABELS).reduce<Array<{ key: string; label: string; value: string }>>(
    (sections, [key, label]) => {
      const value = normalizeDisplayValue(safeResult[key]);
      if (value) {
        sections.push({ key, label, value });
      }
      return sections;
    },
    []
  );

  const structuredSections = Object.entries(STRUCTURED_FIELD_LABELS).reduce<Array<{ key: string; label: string; value: unknown }>>(
    (sections, [key, label]) => {
    const value = safeResult[key];
    if (!value) {
      return sections;
    }

    sections.push({
      key,
      label,
      value,
    });

    return sections;
    },
    []
  );

  return (
    <Card
      title={title}
      className="content-result-panel"
      extra={
        <Space wrap>
          {isStreaming ? <Tag color="processing">流式生成中</Tag> : null}
          {resolvedGenerationId ? <Tag color="blue">记录：{resolvedGenerationId}</Tag> : null}
          <Button icon={<CopyOutlined />} size="small" onClick={() => void copyText(primaryText, '已复制主要结果')}>
            复制结果
          </Button>
          <Button size="small" onClick={() => void copyText(rawJson, '已复制完整 JSON')}>
            复制 JSON
          </Button>
        </Space>
      }
    >
      {shouldShowStreaming ? (
        <div className="content-result-panel__section">
          <Text strong>{isStreaming ? '实时生成内容' : '生成内容预览'}</Text>
          <Paragraph className="content-result-panel__text">{streamingContent}</Paragraph>
        </div>
      ) : null}

      {metaItems.length > 0 ? (
        <Descriptions className="content-result-panel__meta" size="small" column={{ xs: 1, sm: 2 }}>
          {metaItems.map(([key, value]) => (
            <Descriptions.Item key={key} label={FIELD_LABELS[key] ?? key}>
              {String(value)}
            </Descriptions.Item>
          ))}
        </Descriptions>
      ) : null}

      <Space direction="vertical" size="middle" className="content-result-panel__sections">
        {textSections.map((section) => (
          <div key={section.key} className="content-result-panel__section">
            <Text strong>{section.label}</Text>
            <Paragraph className="content-result-panel__text" copyable={{ text: section.value }}>
              {section.value}
            </Paragraph>
          </div>
        ))}

        {structuredSections.map((section) => (
          <div key={section.key} className="content-result-panel__section">
            <Text strong>{section.label}</Text>
            <div
              className="content-result-panel__structured"
              role="article"
              aria-label={`${section.label}结构化结果`}
            >
              {renderStructuredValue(section.value, section.key)}
            </div>
            <Button
              className="content-result-panel__section-copy"
              size="small"
              onClick={() => void copyText(structuredValueToText(section.value) || JSON.stringify(section.value, null, 2), `已复制${section.label}`)}
            >
              复制该部分
            </Button>
          </div>
        ))}
      </Space>

      <Collapse
        className="content-result-panel__collapse"
        items={[
          {
            key: 'raw-json',
            label: '查看原始 JSON',
            children: <pre className="content-result-panel__json">{rawJson}</pre>,
          },
        ]}
      />
    </Card>
  );
};
