import { useEffect, useState } from 'react';
import { Button, Card, Input, Layout, message, Popconfirm, Select, Space, Typography } from 'antd';

import { DocumentList } from '@/components/knowledge/DocumentList';
import { DocumentUpload } from '@/components/knowledge/DocumentUpload';
import { MainLayout } from '@/components/layout/MainLayout';
import { knowledgeService } from '@/services/knowledgeService';
import { useAuthStore } from '@/stores/authStore';
import { useKnowledgeStore } from '@/stores/knowledgeStore';

const { Content } = Layout;
const { Text } = Typography;

const KnowledgePage = () => {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const { documents, knowledgeBases, selectedKnowledgeBaseId, setDocuments, setKnowledgeBases, setSelectedKnowledgeBaseId, setLoading, setError } =
    useKnowledgeStore();
  const [newKnowledgeBaseName, setNewKnowledgeBaseName] = useState('');

  useEffect(() => {
    if (!isAuthenticated) {
      setKnowledgeBases([]);
      setSelectedKnowledgeBaseId(null);
      setDocuments([]);
      return;
    }

    const loadKnowledgeBases = async () => {
      try {
        setLoading(true);
        const response = await knowledgeService.getKnowledgeBases();
        setKnowledgeBases(response.knowledgeBases);
        if (!selectedKnowledgeBaseId && response.knowledgeBases.length > 0) {
          const defaultKnowledgeBase = response.knowledgeBases.find((item) => item.isDefault) || response.knowledgeBases[0];
          setSelectedKnowledgeBaseId(defaultKnowledgeBase.knowledgeBaseId);
        }
      } catch (error: any) {
        setError(error.message || '加载知识库失败');
      } finally {
        setLoading(false);
      }
    };

    void loadKnowledgeBases();
  }, [isAuthenticated, setDocuments, setError, setKnowledgeBases, setLoading, setSelectedKnowledgeBaseId]);

  useEffect(() => {
    if (!isAuthenticated) {
      setDocuments([]);
      return;
    }

    const loadDocuments = async () => {
      if (!selectedKnowledgeBaseId) {
        setDocuments([]);
        return;
      }

      try {
        setLoading(true);
        const response = await knowledgeService.getDocuments(selectedKnowledgeBaseId);
        setDocuments(response.documents);
      } catch (error: any) {
        setError(error.message || '加载文档失败');
      } finally {
        setLoading(false);
      }
    };

    void loadDocuments();
  }, [isAuthenticated, selectedKnowledgeBaseId, setDocuments, setError, setLoading]);

  const handleCreateKnowledgeBase = async () => {
    const name = newKnowledgeBaseName.trim();
    if (!name) {
      message.warning('请输入知识库名称');
      return;
    }

    try {
      const knowledgeBase = await knowledgeService.createKnowledgeBase(name);
      message.success('知识库创建成功');
      setNewKnowledgeBaseName('');
      const response = await knowledgeService.getKnowledgeBases();
      setKnowledgeBases(response.knowledgeBases);
      setSelectedKnowledgeBaseId(knowledgeBase.knowledgeBaseId);
    } catch (error: any) {
      message.error(error.message || '知识库创建失败');
    }
  };

  const handleDeleteKnowledgeBase = async () => {
    if (!selectedKnowledgeBaseId) return;
    try {
      await knowledgeService.deleteKnowledgeBase(selectedKnowledgeBaseId);
      message.success('知识库删除成功');
      setSelectedKnowledgeBaseId(null);
      setDocuments([]);
      const response = await knowledgeService.getKnowledgeBases();
      setKnowledgeBases(response.knowledgeBases);
    } catch (error: any) {
      message.error(error.message || '知识库删除失败');
    }
  };

  return (
    <MainLayout>
      <Content style={{ padding: '24px' }}>
        <Card title="知识库管理" style={{ marginBottom: '24px' }}>
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Space wrap>
              <Text>当前知识库</Text>
              <Select
                style={{ minWidth: 260 }}
                placeholder="请选择知识库"
                value={selectedKnowledgeBaseId || undefined}
                onChange={(value) => setSelectedKnowledgeBaseId(value || null)}
                options={knowledgeBases.map((item) => ({
                  label: item.isDefault ? `${item.name}（默认）` : item.name,
                  value: item.knowledgeBaseId,
                }))}
              />
              <Popconfirm title="确认删除当前知识库吗？这会删除该知识库下所有文档。" onConfirm={handleDeleteKnowledgeBase} okText="确认" cancelText="取消" disabled={!selectedKnowledgeBaseId}>
                <Button danger disabled={!selectedKnowledgeBaseId || knowledgeBases.length <= 1}>删除当前知识库</Button>
              </Popconfirm>
            </Space>
            <Space.Compact style={{ width: '100%' }}>
              <Input placeholder="输入新知识库名称，例如：产品手册库" value={newKnowledgeBaseName} onChange={(event) => setNewKnowledgeBaseName(event.target.value)} onPressEnter={handleCreateKnowledgeBase} />
              <Button type="primary" onClick={handleCreateKnowledgeBase}>创建知识库</Button>
            </Space.Compact>
            <DocumentUpload knowledgeBaseId={selectedKnowledgeBaseId} onUploadSuccess={async () => {
              if (!selectedKnowledgeBaseId) return;
              const response = await knowledgeService.getDocuments(selectedKnowledgeBaseId);
              setDocuments(response.documents);
            }} />
          </Space>
        </Card>
        <Card title="文档列表">
          <DocumentList documents={documents} onDelete={async () => {
            if (!selectedKnowledgeBaseId) return;
            const response = await knowledgeService.getDocuments(selectedKnowledgeBaseId);
            setDocuments(response.documents);
          }} />
        </Card>
      </Content>
    </MainLayout>
  );
};

export default KnowledgePage;
