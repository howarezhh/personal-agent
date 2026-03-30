import type { Document } from '@/types';

export const documentStatusLabelMap: Record<string, string> = {
  pending: '等待中',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
};

export const documentStageLabelMap: Record<string, string> = {
  pending: '等待处理',
  queued: '排队中',
  parsing: '解析文档',
  chunking: '切分文本',
  saving_chunks: '保存分块',
  vectorizing: '生成向量',
  vectorizing_failed: '向量化失败',
  vectorizing_partial: '部分向量化完成',
  summarizing: '生成摘要',
  completed: '处理完成',
  failed: '处理失败',
};

export const getDocumentStatusLabel = (status?: Document['status'] | string) => {
  if (!status) {
    return '已完成';
  }

  return documentStatusLabelMap[status] || status;
};

export const getDocumentStageLabel = (stage?: string) => {
  if (!stage) {
    return undefined;
  }

  return documentStageLabelMap[stage] || stage;
};
