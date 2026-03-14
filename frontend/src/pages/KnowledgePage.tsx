import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Input, Layout, Progress, message, Popconfirm, Select, Space, Tag, Typography } from 'antd';

import { DocumentList } from '@/components/knowledge/DocumentList';
import { DocumentUpload } from '@/components/knowledge/DocumentUpload';
import { MainLayout } from '@/components/layout/MainLayout';
import { knowledgeService } from '@/services/knowledgeService';
import type { FullVectorRebuildTaskResponse } from '@/services/knowledgeService';
import { useAuthStore } from '@/stores/authStore';
import { useKnowledgeStore } from '@/stores/knowledgeStore';

const { Content } = Layout;
const { Text } = Typography;

const fullRebuildTaskStatusMap: Record<FullVectorRebuildTaskResponse['status'], { color: string; label: string }> = {
  pending: { color: 'default', label: '等待中' },
  running: { color: 'processing', label: '执行中' },
  succeeded: { color: 'success', label: '已完成' },
  failed: { color: 'error', label: '失败' },
};

const KnowledgePage = () => {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const {
    documents,
    knowledgeBases,
    selectedKnowledgeBaseId,
    setDocuments,
    setKnowledgeBases,
    setSelectedKnowledgeBaseId,
    setLoading,
    setError,
  } = useKnowledgeStore();

  const [newKnowledgeBaseName, setNewKnowledgeBaseName] = useState('');
  const [isRebuildingVectors, setIsRebuildingVectors] = useState(false);
  const [isStartingFullRebuildTask, setIsStartingFullRebuildTask] = useState(false);
  const [fullRebuildTask, setFullRebuildTask] = useState<FullVectorRebuildTaskResponse | null>(null);

  const retryableDocumentCount = useMemo(
    () => documents.filter((document) => document.canRetryVectorization).length,
    [documents]
  );

  const isFullRebuildTaskActive = fullRebuildTask !== null && ['pending', 'running'].includes(fullRebuildTask.status);

  const fullRebuildPercent = useMemo(() => {
    if (!fullRebuildTask) {
      return 0;
    }
    if (fullRebuildTask.status === 'succeeded') {
      return 100;
    }
    if (fullRebuildTask.totalDocuments <= 0) {
      return fullRebuildTask.status === 'running' ? 5 : 0;
    }
    return Math.max(1, Math.min(100, Math.round((fullRebuildTask.processedDocuments / fullRebuildTask.totalDocuments) * 100)));
  }, [fullRebuildTask]);

  const refreshDocuments = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!selectedKnowledgeBaseId) {
        setDocuments([]);
        return;
      }

      try {
        if (!options?.silent) {
          setLoading(true);
        }
        const response = await knowledgeService.getDocuments(selectedKnowledgeBaseId);
        setDocuments(response.documents);
      } catch (error: any) {
        setError(error.message || '加载文档失败');
      } finally {
        if (!options?.silent) {
          setLoading(false);
        }
      }
    },
    [selectedKnowledgeBaseId, setDocuments, setError, setLoading]
  );

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
  }, [isAuthenticated, selectedKnowledgeBaseId, setDocuments, setError, setKnowledgeBases, setLoading, setSelectedKnowledgeBaseId]);

  useEffect(() => {
    if (!isAuthenticated) {
      setDocuments([]);
      return;
    }

    void refreshDocuments();
  }, [isAuthenticated, refreshDocuments, setDocuments]);

  useEffect(() => {
    if (!isAuthenticated || !selectedKnowledgeBaseId) {
      return;
    }

    const hasInFlightDocuments = documents.some((document) => document.status === 'pending' || document.status === 'processing');
    if (!hasInFlightDocuments) {
      return;
    }

    const timer = window.setInterval(() => {
      void refreshDocuments({ silent: true });
    }, 2000);

    return () => {
      window.clearInterval(timer);
    };
  }, [documents, isAuthenticated, refreshDocuments, selectedKnowledgeBaseId]);

  useEffect(() => {
    if (!fullRebuildTask || !['pending', 'running'].includes(fullRebuildTask.status)) {
      return;
    }

    let cancelled = false;

    const pollTaskStatus = async () => {
      try {
        console.info('[knowledge] polling full rebuild task', { taskId: fullRebuildTask.taskId, status: fullRebuildTask.status });
        const nextTask = await knowledgeService.getFullRebuildVectorsTask(fullRebuildTask.taskId);
        if (cancelled) {
          return;
        }

        console.info('[knowledge] full rebuild task status', nextTask);
        setFullRebuildTask(nextTask);

        if (nextTask.status === 'succeeded') {
          await refreshDocuments({ silent: true });
          message.success(
            nextTask.totalDocuments === 0
              ? '全库向量重建完成，没有需要重建的文档。'
              : `全库向量重建完成：成功重建 ${nextTask.totalVectorizedChunksNow} 个 ${nextTask.targetDimension} 维向量分块。`
          );
        }

        if (nextTask.status === 'failed') {
          await refreshDocuments({ silent: true });
          message.warning(
            nextTask.error
              ? `全库向量重建失败：${nextTask.error}`
              : `全库向量重建结束：成功 ${nextTask.succeededDocuments} 个文档，失败 ${nextTask.failedDocuments} 个文档，剩余 ${nextTask.totalMissingChunksAfter} 个分块待处理。`
          );
        }
      } catch (error: any) {
        if (cancelled) {
          return;
        }
        const errorMessage = error?.message || '获取全库向量重建进度失败';
        console.error('[knowledge] full rebuild task polling failed', error);
        setFullRebuildTask((currentTask) =>
          currentTask
            ? {
                ...currentTask,
                status: 'failed',
                error: errorMessage,
              }
            : currentTask
        );
        message.error(errorMessage);
      }
    };

    void pollTaskStatus();
    const timer = window.setInterval(() => {
      void pollTaskStatus();
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [fullRebuildTask, refreshDocuments]);

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
      message.error(error.message || '创建知识库失败');
    }
  };

  const handleDeleteKnowledgeBase = async () => {
    if (!selectedKnowledgeBaseId) {
      return;
    }

    try {
      await knowledgeService.deleteKnowledgeBase(selectedKnowledgeBaseId);
      message.success('知识库删除成功');
      setSelectedKnowledgeBaseId(null);
      setDocuments([]);
      const response = await knowledgeService.getKnowledgeBases();
      setKnowledgeBases(response.knowledgeBases);
    } catch (error: any) {
      message.error(error.message || '删除知识库失败');
    }
  };

  const handleRebuildVectors = async () => {
    if (!selectedKnowledgeBaseId) {
      message.warning('请先选择知识库');
      return;
    }

    try {
      setIsRebuildingVectors(true);
      console.info('[knowledge] rebuildVectors start', { knowledgeBaseId: selectedKnowledgeBaseId });
      const result = await knowledgeService.rebuildVectors(selectedKnowledgeBaseId);
      console.info('[knowledge] rebuildVectors result', result);
      await refreshDocuments({ silent: true });

      if (result.totalDocuments === 0) {
        message.info('当前知识库没有需要重试向量化的文档。');
        return;
      }

      if (result.failedDocuments === 0) {
        message.success(`向量重试完成，新增 ${result.totalVectorizedChunksNow} 个向量分块。`);
        return;
      }

      message.warning(
        `向量重试结束：成功 ${result.succeededDocuments} 个文档，失败 ${result.failedDocuments} 个文档，剩余 ${result.totalMissingChunksAfter} 个分块待处理。`
      );
    } catch (error: any) {
      message.error(error.message || '向量重试失败');
    } finally {
      setIsRebuildingVectors(false);
    }
  };

  const handleFullRebuildVectors = async () => {
    try {
      setIsStartingFullRebuildTask(true);
      console.info('[knowledge] start full rebuild task', { scope: 'all_knowledge_bases' });
      const task = await knowledgeService.startFullRebuildVectorsTask();
      console.info('[knowledge] full rebuild task started', task);
      setFullRebuildTask(task);
      message.info('已启动全库向量重建任务，正在后台执行。');
    } catch (error: any) {
      message.error(error.message || '启动全库向量重建任务失败');
    } finally {
      setIsStartingFullRebuildTask(false);
    }
  };

  const fullRebuildTaskTag = fullRebuildTask ? fullRebuildTaskStatusMap[fullRebuildTask.status] : null;

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
              <Popconfirm
                title="确定删除当前知识库吗？该操作会删除知识库中的所有文档。"
                onConfirm={handleDeleteKnowledgeBase}
                okText="确认"
                cancelText="取消"
                disabled={!selectedKnowledgeBaseId}
              >
                <Button danger disabled={!selectedKnowledgeBaseId || knowledgeBases.length <= 1}>
                  删除知识库
                </Button>
              </Popconfirm>
              <Button
                onClick={handleRebuildVectors}
                loading={isRebuildingVectors}
                disabled={!selectedKnowledgeBaseId || retryableDocumentCount === 0 || isFullRebuildTaskActive || isStartingFullRebuildTask}
              >
                {`重试未向量化分块${retryableDocumentCount > 0 ? `（${retryableDocumentCount}）` : ''}`}
              </Button>
              <Popconfirm
                title="将按当前本地 512 维模型重建全库所有向量，并重置现有向量集合，确认继续吗？"
                onConfirm={handleFullRebuildVectors}
                okText="开始重建"
                cancelText="取消"
                disabled={knowledgeBases.length === 0 || isFullRebuildTaskActive}
              >
                <Button
                  loading={isStartingFullRebuildTask}
                  disabled={knowledgeBases.length === 0 || isRebuildingVectors || isFullRebuildTaskActive}
                >
                  全库重建所有向量
                </Button>
              </Popconfirm>
            </Space>

            {fullRebuildTask && fullRebuildTaskTag ? (
              <Alert
                type={fullRebuildTask.status === 'failed' ? 'error' : fullRebuildTask.status === 'succeeded' ? 'success' : 'info'}
                showIcon
                message={
                  <Space wrap>
                    <span>全库向量重建任务</span>
                    <Tag color={fullRebuildTaskTag.color}>{fullRebuildTaskTag.label}</Tag>
                    <span>任务 ID：{fullRebuildTask.taskId}</span>
                  </Space>
                }
                description={
                  <Space direction="vertical" style={{ width: '100%' }} size="small">
                    <Progress percent={fullRebuildPercent} status={fullRebuildTask.status === 'failed' ? 'exception' : undefined} />
                    <Text>
                      {`已处理 ${fullRebuildTask.processedDocuments}/${fullRebuildTask.totalDocuments} 个文档，成功 ${fullRebuildTask.succeededDocuments} 个，失败 ${fullRebuildTask.failedDocuments} 个，已写入 ${fullRebuildTask.totalVectorizedChunksNow} 个向量分块。`}
                    </Text>
                    {fullRebuildTask.currentFileName ? (
                      <Text type="secondary">当前文件：{fullRebuildTask.currentFileName}</Text>
                    ) : null}
                    <Text type="secondary">
                      {`目标维度：${fullRebuildTask.targetDimension}，向量集合已重置：${fullRebuildTask.resetCollection ? '是' : '否'}。`}
                    </Text>
                    {fullRebuildTask.error ? <Text type="danger">错误信息：{fullRebuildTask.error}</Text> : null}
                  </Space>
                }
              />
            ) : null}

            <Space.Compact style={{ width: '100%' }}>
              <Input
                placeholder="请输入新知识库名称"
                value={newKnowledgeBaseName}
                onChange={(event) => setNewKnowledgeBaseName(event.target.value)}
                onPressEnter={handleCreateKnowledgeBase}
              />
              <Button type="primary" onClick={handleCreateKnowledgeBase}>
                创建知识库
              </Button>
            </Space.Compact>

            <DocumentUpload
              knowledgeBaseId={selectedKnowledgeBaseId}
              onUploadSuccess={async () => {
                await refreshDocuments({ silent: true });
              }}
            />
          </Space>
        </Card>
        <Card title="文档列表">
          <DocumentList
            documents={documents}
            onDelete={async () => {
              await refreshDocuments({ silent: true });
            }}
          />
        </Card>
      </Content>
    </MainLayout>
  );
};

export default KnowledgePage;
