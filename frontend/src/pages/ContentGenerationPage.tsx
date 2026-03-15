import { useMemo, useState, type ReactNode } from 'react';
import { Card, Col, Row, Space, Tabs, Tag, Typography } from 'antd';
import { BookOutlined, EditOutlined, RocketOutlined, VideoCameraOutlined } from '@ant-design/icons';

import { ContentOptimizer } from '@/components/content/ContentOptimizer';
import { NovelGenerator } from '@/components/content/NovelGenerator';
import { ScriptGenerator } from '@/components/content/ScriptGenerator';
import { MainLayout } from '@/components/layout/MainLayout';

import './ContentGenerationPage.css';

const { Paragraph, Title, Text } = Typography;

type ContentTabKey = 'novel' | 'script' | 'optimizer';

const tabMeta: Record<ContentTabKey, { title: string; description: string; icon: JSX.Element }> = {
  novel: {
    title: '小说生成',
    description: '覆盖大纲、章节、角色、世界观与续写场景。',
    icon: <BookOutlined />,
  },
  script: {
    title: '脚本生成',
    description: '支持大纲、场景、对白、分镜与完整脚本草案。',
    icon: <VideoCameraOutlined />,
  },
  optimizer: {
    title: '内容优化',
    description: '聚焦润色、改写、扩写、摘要与 SEO 优化。',
    icon: <EditOutlined />,
  },
};

const capabilityCards = [
  {
    title: '统一内容 API',
    description: '页面动作全部走 `/api/v1/content` 统一接口，生成结果自动记录到后端内容生成表。',
  },
  {
    title: '流式结果展示',
    description: '生成内容边输出边展示，完整结果和结构化 JSON 会在右侧统一回显。',
  },
  {
    title: '工作台式交互',
    description: '左侧填写需求，右侧实时查看结果，减少来回滚动和信息切换。',
  },
];

const ContentGenerationPage = () => {
  const [activeTab, setActiveTab] = useState<ContentTabKey>('novel');

  const currentTab = useMemo(() => tabMeta[activeTab], [activeTab]);

  return (
    <MainLayout>
      <div className="content-generation-page">
        <Card className="content-generation-page__hero" bordered={false}>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Space wrap>
              <Tag color="blue">内容生成工作台</Tag>
              <Tag color="purple">统一前后端契约</Tag>
              <Tag color="geekblue">生成记录自动入库</Tag>
            </Space>

            <Space align="start" size="middle" wrap>
              <div className="content-generation-page__hero-icon">
                <RocketOutlined />
              </div>
              <div>
                <Title level={2} className="content-generation-page__title">
                  内容生成
                </Title>
                <Paragraph className="content-generation-page__subtitle">
                  把小说创作、脚本输出和文本优化集中在一个页面中，统一表单体验、统一返回结构、统一结果回显。
                </Paragraph>
                <Text type="secondary">
                  当前模式：{currentTab.title} · {currentTab.description}
                </Text>
              </div>
            </Space>
          </Space>
        </Card>

        <Row gutter={[16, 16]} className="content-generation-page__summary">
          {capabilityCards.map((item) => (
            <Col xs={24} md={8} key={item.title}>
              <Card className="content-generation-page__summary-card" bordered={false}>
                <Text strong>{item.title}</Text>
                <Paragraph className="content-generation-page__summary-text">{item.description}</Paragraph>
              </Card>
            </Col>
          ))}
        </Row>

        <Card className="content-generation-page__tabs-card" bordered={false}>
          <Tabs
            activeKey={activeTab}
            onChange={(key) => setActiveTab(key as ContentTabKey)}
            size="large"
            items={(
              [
                {
                  key: 'novel',
                  label: (
                    <Space size="small">
                      {tabMeta.novel.icon}
                      <span>{tabMeta.novel.title}</span>
                    </Space>
                  ),
                  children: <NovelGenerator />,
                },
                {
                  key: 'script',
                  label: (
                    <Space size="small">
                      {tabMeta.script.icon}
                      <span>{tabMeta.script.title}</span>
                    </Space>
                  ),
                  children: <ScriptGenerator />,
                },
                {
                  key: 'optimizer',
                  label: (
                    <Space size="small">
                      {tabMeta.optimizer.icon}
                      <span>{tabMeta.optimizer.title}</span>
                    </Space>
                  ),
                  children: <ContentOptimizer />,
                },
              ] satisfies { key: ContentTabKey; label: ReactNode; children: ReactNode }[]
            )}
          />
        </Card>
      </div>
    </MainLayout>
  );
};

export default ContentGenerationPage;
