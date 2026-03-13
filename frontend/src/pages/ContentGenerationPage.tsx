/**
 * 内容生成页面
 * 提供小说生成、脚本生成、内容优化功能
 */

import React, { useState } from 'react';
import { Tabs, Card } from 'antd';
import { BookOutlined, VideoCameraOutlined, EditOutlined } from '@ant-design/icons';
import { MainLayout } from '@/components/layout/MainLayout';
import { NovelGenerator } from '@/components/content/NovelGenerator';
import { ScriptGenerator } from '@/components/content/ScriptGenerator';
import { ContentOptimizer } from '@/components/content/ContentOptimizer';
import './ContentGenerationPage.css';

const { TabPane } = Tabs;

const ContentGenerationPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<string>('novel');

  return (
    <MainLayout>
      <div className="content-generation-page">
        <div className="page-header">
          <h1>内容生成</h1>
          <p>使用AI创作小说、脚本和优化内容</p>
        </div>

        <Card className="content-tabs-card">
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            size="large"
            tabBarStyle={{ marginBottom: 24 }}
          >
            <TabPane
              tab={
                <span>
                  <BookOutlined />
                  小说生成
                </span>
              }
              key="novel"
            >
              <NovelGenerator />
            </TabPane>
            <TabPane
              tab={
                <span>
                  <VideoCameraOutlined />
                  脚本生成
                </span>
              }
              key="script"
            >
              <ScriptGenerator />
            </TabPane>
            <TabPane
              tab={
                <span>
                  <EditOutlined />
                  内容优化
                </span>
              }
              key="optimizer"
            >
              <ContentOptimizer />
            </TabPane>
          </Tabs>
        </Card>
      </div>
    </MainLayout>
  );
};

export default ContentGenerationPage;
