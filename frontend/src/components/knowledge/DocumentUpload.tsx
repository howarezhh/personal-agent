import { useState } from 'react';
import { Upload, Button, message } from 'antd';
import { UploadOutlined } from '@ant-design/icons';
import type { UploadProps } from 'antd';

import { knowledgeService } from '@/services/knowledgeService';

interface DocumentUploadProps {
  knowledgeBaseId?: string | null;
  onUploadSuccess?: () => void;
}

const ACCEPTED_EXTENSIONS = [
  'txt', 'md', 'markdown', 'rst', 'log',
  'py', 'js', 'ts', 'tsx', 'jsx', 'java', 'c', 'cpp', 'h', 'hpp', 'go', 'rs',
  'sh', 'bash', 'bat', 'ps1', 'sql', 'json', 'yaml', 'yml', 'xml', 'html', 'css',
  'scss', 'less', 'vue', 'ini', 'conf', 'toml', 'env', 'properties',
  'pdf', 'docx', 'xlsx', 'csv', 'tsv',
] as const;

const ACCEPT_ATTR = ACCEPTED_EXTENSIONS.map((ext) => `.${ext}`).join(',');

type BeforeUploadHandler = NonNullable<UploadProps['beforeUpload']>;

const isAcceptedExtension = (filename: string) => {
  const fileExtension = filename.split('.').pop()?.toLowerCase() || '';

  return {
    fileExtension,
    isAccepted: ACCEPTED_EXTENSIONS.includes(fileExtension as (typeof ACCEPTED_EXTENSIONS)[number]),
  };
};

export const DocumentUpload = ({ knowledgeBaseId, onUploadSuccess }: DocumentUploadProps) => {
  const [uploading, setUploading] = useState(false);

  const isDisabled = !knowledgeBaseId || uploading;

  const handleBeforeUpload: BeforeUploadHandler = async (file) => {
    if (!knowledgeBaseId) {
      message.warning('请先选择知识库');
      return Upload.LIST_IGNORE;
    }

    if (uploading) {
      return Upload.LIST_IGNORE;
    }

    const { fileExtension, isAccepted } = isAcceptedExtension(file.name);

    if (!isAccepted) {
      message.error(`不支持的文件类型: ${fileExtension || '未知类型'}`);
      return Upload.LIST_IGNORE;
    }

    try {
      console.log(`[KnowledgeUpload] 开始上传文档: ${file.name}, knowledgeBaseId=${knowledgeBaseId}`);
      setUploading(true);
      await knowledgeService.uploadDocument(file, knowledgeBaseId);
      console.log(`[KnowledgeUpload] 文档上传成功: ${file.name}`);
      message.success('文档上传成功');
      onUploadSuccess?.();
    } catch (error: unknown) {
      console.error('[KnowledgeUpload] 文档上传失败:', error);
      const errorMessage = error instanceof Error ? error.message : '文档上传失败';
      message.error(errorMessage);
    } finally {
      setUploading(false);
    }

    return Upload.LIST_IGNORE;
  };

  return (
    <Upload
      name="file"
      multiple={false}
      accept={ACCEPT_ATTR}
      disabled={isDisabled}
      beforeUpload={handleBeforeUpload}
      showUploadList={false}
    >
      <Button icon={<UploadOutlined />} loading={uploading} disabled={isDisabled}>
        上传文档
      </Button>
    </Upload>
  );
};
