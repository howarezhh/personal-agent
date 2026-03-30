import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Input, Layout, Progress, message, Popconfirm, Select, Space, Tag, Typography } from 'antd';

import { DocumentList } from '@/components/knowledge/DocumentList';
import { DocumentUpload } from '@/components/knowledge/DocumentUpload';
import { MainLayout } from '@/components/layout/MainLayout';
import { knowledgeService } from '@/services/knowledgeService';
import type { FullVectorRebuildTaskResponse } from '@/services/knowledgeService';
import { useAuthStore } from '@/stores/authStore';
import { useKnowledgeStore } from '@/stores/knowledgeStore';

import './KnowledgePage.css';

const { Content } = Layout;
const { Text } = Typography;

const fullRebuildTaskStatusMap: Record<FullVectorRebuildTaskResponse['status'], { color: string; label: string }> = {
  pending: { color: 'default', label: '等待中' },
  running: { color: 'processing', label: '执行中' },
  succeeded: { color: 'success', label: '已完成' },
  failed: { color: 'error', label: '失败' },
};

// 统一提取错误信息，避免页面逻辑散落类型判断。
const getErrorMessage = (error: unknown, fallback: string) => {
  return error instanceof Error ? error.message : fallback;
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

    return Math.max(
      1,
      Math.min(100, Math.round((fullRebuildTask.processedDocuments / fullRebuildTask.totalDocuments) * 100))
    );
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
      } catch (error: unknown) {
        setError(getErrorMessage(error, '加载文档失败'));
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
      setFullRebuildTask(null);
      return;
    }

    const loadKnowledgeBases = async () => {
      try {
        setLoading(true);
        const response = await knowledgeService.getKnowledgeBases();
        setKnowledgeBases(response.knowledgeBases);

        if (response.knowledgeBases.length === 0) {
          setSelectedKnowledgeBaseId(null);
          return;
        }

        const currentExists = response.knowledgeBases.some(
          (item) => item.knowledgeBaseId === selectedKnowledgeBaseId
        );

        if (!currentExists) {
          const defaultKnowledgeBase = response.knowledgeBases.find((item) => item.isDefault) || response.knowledgeBases[0];
          setSelectedKnowledgeBaseId(defaultKnowledgeBase.knowledgeBaseId);
        }
      } catch (error: unknown) {
        setError(getErrorMessage(error, '加载知识库失败'));
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

    const hasInFlightDocuments = documents.some(
      (document) => document.status === 'pending' || document.status === 'processing'
    );

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

    // 全库重建任务在后台执行，这里轮询任务状态并同步前端进度。
    const pollTaskStatus = async () => {
      try {
        const nextTask = await knowledgeService.getFullRebuildVectorsTask(fullRebuildTask.taskId);
        if (cancelled) {
          return;
        }

        setFullRebuildTask(nextTask);

        const rebuildScopeLabel = nextTask.scope === 'knowledge_base' ? '当前知识库' : '全库';

        if (nextTask.status === 'succeeded') {
          await refreshDocuments({ silent: true });
          message.success(
            nextTask.totalDocuments === 0
              ? `${rebuildScopeLabel}向量重建完成，没有需要处理的文档。`
              : `${rebuildScopeLabel}向量重建完成：新增 ${nextTask.totalVectorizedChunksNow} 个 ${nextTask.targetDimension} 维向量分块。`
          );
        }

        if (nextTask.status === 'failed') {
          await refreshDocuments({ silent: true });
          message.warning(
            nextTask.error
              ? `${rebuildScopeLabel}向量重建失败：${nextTask.error}`
              : `${rebuildScopeLabel}向量重建结束：成功 ${nextTask.succeededDocuments} 个文档，失败 ${nextTask.failedDocuments} 个文档，剩余 ${nextTask.totalMissingChunksAfter} 个分块待处理。`
          );
        }
      } catch (error: unknown) {
        if (cancelled) {
          return;
        }

        const errorMessage = getErrorMessage(error, '获取全库向量重建进度失败');
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
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '创建知识库失败'));
    }
  };

  const handleDeleteKnowledgeBase = async () => {
    if (!selectedKnowledgeBaseId) {
      return;
    }

    try {
      await knowledgeService.deleteKnowledgeBase(selectedKnowledgeBaseId);
      message.success('知识库删除成功');
      setDocuments([]);

      const response = await knowledgeService.getKnowledgeBases();
      setKnowledgeBases(response.knowledgeBases);

      const defaultKnowledgeBase = response.knowledgeBases.find((item) => item.isDefault) || response.knowledgeBases[0];
      setSelectedKnowledgeBaseId(defaultKnowledgeBase?.knowledgeBaseId ?? null);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '删除知识库失败'));
    }
  };

  const handleRebuildVectors = async () => {
    if (!selectedKnowledgeBaseId) {
      message.warning('请先选择知识库');
      return;
    }

    try {
      setIsRebuildingVectors(true);
      const result = await knowledgeService.rebuildVectors(selectedKnowledgeBaseId);
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
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '向量重试失败'));
    } finally {
      setIsRebuildingVectors(false);
    }
  };

  const handleFullRebuildVectors = async () => {
    if (!selectedKnowledgeBaseId) {
      message.warning('请先选择一个知识库');
      return;
    }

    try {
      setIsStartingFullRebuildTask(true);
      const task = await knowledgeService.startFullRebuildVectorsTask(selectedKnowledgeBaseId);
      setFullRebuildTask(task);
      message.info('已启动当前知识库向量重建任务，正在后台执行。');
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '启动当前知识库向量重建任务失败'));
    } finally {
      setIsStartingFullRebuildTask(false);
    }
  };

  const fullRebuildTaskTag = fullRebuildTask ? fullRebuildTaskStatusMap[fullRebuildTask.status] : null;

  return (
    <MainLayout>
      <Content className="app-page-scroll knowledge-page">
        <Card title="知识库管理" className="knowledge-page__card">
          <Space direction="vertical" className="knowledge-page__stack" size="middle">
            {/* 工具栏允许自动换行，避免较窄电脑屏幕下控件被挤出可视区域 */}
            <Space wrap className="knowledge-page__toolbar">
              <Text>当前知识库</Text>
              <Select
                className="knowledge-page__selector"
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
                disabled={
                  !selectedKnowledgeBaseId ||
                  retryableDocumentCount === 0 ||
                  isFullRebuildTaskActive ||
                  isStartingFullRebuildTask
                }
              >
                {`重试缺失向量块${retryableDocumentCount > 0 ? `（${retryableDocumentCount}）` : ''}`}
              </Button>
              <Popconfirm
                title="将按当前本地 512 维模型重建当前选中知识库的全部向量，并重置该知识库对应的现有向量集合，确认继续吗？"
                onConfirm={handleFullRebuildVectors}
                okText="开始重建"
                cancelText="取消"
                disabled={!selectedKnowledgeBaseId || isFullRebuildTaskActive}
              >
                <Button
                  loading={isStartingFullRebuildTask}
                  disabled={!selectedKnowledgeBaseId || isRebuildingVectors || isFullRebuildTaskActive}
                >
                  重建当前知识库全部向量
                </Button>
              </Popconfirm>
            </Space>

            {fullRebuildTask && fullRebuildTaskTag ? (
              <Alert
                type={fullRebuildTask.status === 'failed' ? 'error' : fullRebuildTask.status === 'succeeded' ? 'success' : 'info'}
                showIcon
                message={
                  <Space wrap>
                    <span>{fullRebuildTask.scope === 'knowledge_base' ? '当前知识库向量重建任务' : '全库向量重建任务'}</span>
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
                      {`重建范围：${fullRebuildTask.scope === 'knowledge_base' ? '当前知识库' : '全部知识库'}。`}
                    </Text>
                    <Text type="secondary">
                      {`目标维度：${fullRebuildTask.targetDimension}，向量集合已重置：${fullRebuildTask.resetCollection ? '是' : '否'}。`}
                    </Text>
                    {fullRebuildTask.error ? <Text type="danger">错误信息：{fullRebuildTask.error}</Text> : null}
                  </Space>
                }
              />
            ) : null}

            {/* 新建知识库区域改为可换行布局，输入框和按钮会随容器宽度自适应 */}
            <div className="knowledge-page__create">
              <Input
                className="knowledge-page__create-input"
                placeholder="请输入新知识库名称"
                value={newKnowledgeBaseName}
                onChange={(event) => setNewKnowledgeBaseName(event.target.value)}
                onPressEnter={handleCreateKnowledgeBase}
              />
              <Button className="knowledge-page__create-button" type="primary" onClick={handleCreateKnowledgeBase}>
                创建知识库
              </Button>
            </div>

            <DocumentUpload
              knowledgeBaseId={selectedKnowledgeBaseId}
              onUploadSuccess={async () => {
                await refreshDocuments({ silent: true });
              }}
            />
          </Space>
        </Card>

        <Card title="文档列表" className="knowledge-page__document-card">
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

