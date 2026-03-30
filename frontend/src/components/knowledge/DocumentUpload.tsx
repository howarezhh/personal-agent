import { useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { Button, List, Progress, Space, Tag, Typography, message } from 'antd';
import { ClearOutlined, UploadOutlined } from '@ant-design/icons';

import { knowledgeService } from '@/services/knowledgeService';
import type { DocumentUploadResponse } from '@/types';
import { getDocumentStageLabel } from '@/utils/knowledgeStatus';

interface DocumentUploadProps {
  knowledgeBaseId?: string | null;
  onUploadSuccess?: () => void | Promise<void>;
}

type UploadTaskStatus = 'uploading' | 'processing' | 'completed' | 'failed';

type UploadResult = { success: true } | { success: false; errorMessage: string };
type UploadSettledResult = PromiseSettledResult<UploadResult>;
type NormalizedUploadDocument = DocumentUploadResponse & { status: string };

interface UploadTaskItem {
  id: string;
  documentId?: string;
  fileName: string;
  progress: number;
  status: UploadTaskStatus;
  stage?: string;
  error?: string;
}

const ACCEPTED_EXTENSIONS = [
  'txt', 'md', 'markdown', 'rst', 'log',
  'py', 'js', 'ts', 'tsx', 'jsx', 'java', 'c', 'cpp', 'h', 'hpp', 'go', 'rs',
  'sh', 'bash', 'bat', 'ps1', 'sql', 'json', 'yaml', 'yml', 'xml', 'html', 'css',
  'scss', 'less', 'vue', 'ini', 'conf', 'toml', 'env', 'properties',
  'pdf', 'docx', 'xlsx', 'csv', 'tsv',
] as const;

const ACCEPT_ATTR = ACCEPTED_EXTENSIONS.map((ext) => `.${ext}`).join(',');

const statusTagConfig: Record<UploadTaskStatus, { color: string; label: string }> = {
  uploading: { color: 'processing', label: '上传中' },
  processing: { color: 'warning', label: '处理中' },
  completed: { color: 'success', label: '成功' },
  failed: { color: 'error', label: '失败' },
};

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

const isAcceptedExtension = (filename: string) => {
  const fileExtension = filename.split('.').pop()?.toLowerCase() || '';

  return {
    fileExtension,
    isAccepted: ACCEPTED_EXTENSIONS.includes(fileExtension as (typeof ACCEPTED_EXTENSIONS)[number]),
  };
};

const normalizeUploadResult = (document: DocumentUploadResponse): NormalizedUploadDocument => ({
  ...document,
  status: document.status ?? 'processing',
});

export const DocumentUpload = ({ knowledgeBaseId, onUploadSuccess }: DocumentUploadProps) => {
  const singleInputRef = useRef<HTMLInputElement>(null);
  const batchInputRef = useRef<HTMLInputElement>(null);
  const [uploadTasks, setUploadTasks] = useState<UploadTaskItem[]>([]);

  const isUploading = uploadTasks.some((task) => task.status === 'uploading' || task.status === 'processing');
  const isDisabled = !knowledgeBaseId || isUploading;

  const updateTask = (taskId: string, updater: (task: UploadTaskItem) => UploadTaskItem) => {
    setUploadTasks((currentTasks) => currentTasks.map((task) => (task.id === taskId ? updater(task) : task)));
  };

  const pollDocumentStatus = async (taskId: string, documentId: string): Promise<UploadResult> => {
    while (true) {
      try {
        const document = normalizeUploadResult(await knowledgeService.getDocumentStatus(documentId));
        const normalizedProgress = Math.max(1, Math.min(100, document.processingProgress ?? 100));
        const taskStatus: UploadTaskStatus =
          document.status === 'completed'
            ? 'completed'
            : document.status === 'failed'
              ? 'failed'
              : 'processing';

        updateTask(taskId, (task) => ({
          ...task,
          documentId,
          progress: normalizedProgress,
          status: taskStatus,
          stage: document.processingStage,
          error: document.errorMessage,
        }));

        if (document.status === 'completed') {
          return { success: true };
        }

        if (document.status === 'failed') {
          return { success: false, errorMessage: document.errorMessage || '文档处理失败' };
        }

        await sleep(1000);
      } catch (error: unknown) {
        const errorMessage = error instanceof Error ? error.message : '文档处理失败';
        updateTask(taskId, (task) => ({
          ...task,
          documentId,
          status: 'failed',
          error: errorMessage,
        }));
        return { success: false, errorMessage };
      }
    }
  };

  const normalizeSelectedFiles = (files: File[]) => {
    const validFiles: File[] = [];

    files.forEach((file) => {
      const { fileExtension, isAccepted } = isAcceptedExtension(file.name);
      if (!isAccepted) {
        message.error(`不支持的文件类型: ${fileExtension || '未知类型'} (${file.name})`);
        return;
      }
      validFiles.push(file);
    });

    return validFiles;
  };

  const createTaskEntries = (files: File[]) =>
    files.map((file, index) => ({
      id: `${Date.now()}-${index}-${file.name}`,
      fileName: file.name,
      progress: 0,
      status: 'uploading' as const,
    }));

  const createRefreshTrigger = () => {
    let acceptedRefreshTriggered = false;

    return async () => {
      if (acceptedRefreshTriggered) {
        return;
      }
      acceptedRefreshTriggered = true;
      await onUploadSuccess?.();
    };
  };

  const handleAcceptedDocument = async (taskId: string, rawDocument: DocumentUploadResponse): Promise<UploadResult> => {
    const document = normalizeUploadResult(rawDocument);

    updateTask(taskId, (task) => ({
      ...task,
      documentId: document.documentId,
      progress: Math.max(task.progress, document.processingProgress ?? 100),
      status: document.status === 'completed' ? 'completed' : document.status === 'failed' ? 'failed' : 'processing',
      stage: document.processingStage,
      error: document.errorMessage,
    }));

    if (document.status === 'completed') {
      updateTask(taskId, (task) => ({
        ...task,
        progress: 100,
        status: 'completed',
        stage: document.processingStage,
        error: undefined,
      }));
      return { success: true };
    }

    if (document.status === 'failed') {
      return { success: false, errorMessage: document.errorMessage || '文档上传失败' };
    }

    return pollDocumentStatus(taskId, document.documentId);
  };

  const uploadSingleFile = async (file: File, taskId: string): Promise<UploadResult> => {
    try {
      const document = await knowledgeService.uploadDocument(file, knowledgeBaseId!, {
        onProgress: (percent) => {
          updateTask(taskId, (task) => ({
            ...task,
            progress: percent,
            status: percent >= 100 ? 'processing' : 'uploading',
          }));
        },
      });

      return handleAcceptedDocument(taskId, document);
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : '文档上传失败';
      updateTask(taskId, (task) => ({
        ...task,
        status: 'failed',
        error: errorMessage,
      }));
      return { success: false, errorMessage };
    }
  };

  const uploadBatchFiles = async (files: File[], taskEntries: UploadTaskItem[]): Promise<UploadSettledResult[]> => {
    const taskByFileName = new Map(taskEntries.map((task) => [task.fileName, task.id]));

    taskEntries.forEach((task) => {
      updateTask(task.id, (current) => ({
        ...current,
        progress: 10,
        status: 'uploading',
      }));
    });

    try {
      const result = await knowledgeService.uploadDocumentsBatch(files, knowledgeBaseId!);
      return Promise.allSettled(
        result.results.map(async (item): Promise<UploadResult> => {
          const taskId = taskByFileName.get(item.fileName);
          if (!taskId) {
            return { success: false, errorMessage: item.error || '未找到上传任务' };
          }

          if (!item.success || !item.document) {
            const errorMessage = item.error || '文档上传失败';
            updateTask(taskId, (task) => ({
              ...task,
              status: 'failed',
              error: errorMessage,
            }));
            return { success: false, errorMessage };
          }

          return handleAcceptedDocument(taskId, item.document);
        })
      );
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : '批量上传失败';
      taskEntries.forEach((task) => {
        updateTask(task.id, (current) => ({
          ...current,
          status: 'failed',
          error: errorMessage,
        }));
      });
      return taskEntries.map((): UploadSettledResult => ({ status: 'fulfilled', value: { success: false, errorMessage } }));
    }
  };

  const uploadFiles = async (files: File[]) => {
    if (!knowledgeBaseId) {
      message.warning('请先选择知识库');
      return;
    }

    const validFiles = normalizeSelectedFiles(files);
    if (validFiles.length === 0) {
      return;
    }

    const taskEntries = createTaskEntries(validFiles);
    setUploadTasks((currentTasks) => [...taskEntries, ...currentTasks]);

    const triggerAcceptedRefresh = createRefreshTrigger();
    let settledResults: UploadSettledResult[];

    if (validFiles.length === 1) {
      settledResults = await Promise.allSettled([uploadSingleFile(validFiles[0], taskEntries[0].id)]);
    } else {
      settledResults = await uploadBatchFiles(validFiles, taskEntries);
    }

    const successCount = settledResults.filter((result) => result.status === 'fulfilled' && result.value.success).length;
    const failedResults = settledResults.filter(
      (result): result is PromiseFulfilledResult<{ success: false; errorMessage: string }> =>
        result.status === 'fulfilled' && !result.value.success
    );

    if (successCount > 0) {
      await triggerAcceptedRefresh();
    }

    if (failedResults.length === 0) {
      message.success(successCount > 1 ? `批量上传完成，共成功 ${successCount} 个文档` : '文档上传成功');
      return;
    }

    if (successCount > 0) {
      message.warning(`上传完成：成功 ${successCount} 个，失败 ${failedResults.length} 个`);
      return;
    }

    message.error(failedResults[0].value.errorMessage || '文档上传失败');
  };

  const handleInputChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(event.target.files ?? []);
    event.target.value = '';
    await uploadFiles(selectedFiles);
  };

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <Space wrap>
        <Button icon={<UploadOutlined />} disabled={isDisabled} onClick={() => singleInputRef.current?.click()}>
          上传文档
        </Button>
        <Button icon={<UploadOutlined />} disabled={isDisabled} onClick={() => batchInputRef.current?.click()}>
          批量上传文档
        </Button>
        <Button icon={<ClearOutlined />} disabled={isUploading || uploadTasks.length === 0} onClick={() => setUploadTasks([])}>
          清空记录
        </Button>
        {!knowledgeBaseId ? <Typography.Text type="secondary">请先选择知识库后再上传</Typography.Text> : null}
      </Space>

      <input
        ref={singleInputRef}
        type="file"
        accept={ACCEPT_ATTR}
        style={{ display: 'none' }}
        onChange={(event) => {
          void handleInputChange(event);
        }}
      />
      <input
        ref={batchInputRef}
        type="file"
        multiple
        accept={ACCEPT_ATTR}
        style={{ display: 'none' }}
        onChange={(event) => {
          void handleInputChange(event);
        }}
      />

      {uploadTasks.length > 0 ? (
        <List
          size="small"
          bordered
          dataSource={uploadTasks}
          renderItem={(task) => {
            const statusTag = statusTagConfig[task.status];
            return (
              <List.Item>
                <Space direction="vertical" style={{ width: '100%' }} size={4}>
                  <Space style={{ justifyContent: 'space-between', width: '100%' }} wrap>
                    <Typography.Text>{task.fileName}</Typography.Text>
                    <Tag color={statusTag.color}>
                      {task.stage ? `${statusTag.label} / ${getDocumentStageLabel(task.stage)}` : statusTag.label}
                    </Tag>
                  </Space>
                  <Progress
                    percent={task.progress}
                    size="small"
                    status={task.status === 'failed' ? 'exception' : task.status === 'completed' ? 'success' : 'active'}
                  />
                  {task.error ? <Typography.Text type="danger">{task.error}</Typography.Text> : null}
                </Space>
              </List.Item>
            );
          }}
        />
      ) : null}
    </Space>
  );
};


