import { DeleteOutlined, FileTextOutlined, SyncOutlined } from '@ant-design/icons';
import { Button, message, Popconfirm, Progress, Space, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';

import { knowledgeService } from '@/services/knowledgeService';
import type { Document } from '@/types';
import { formatDate, formatFileSize } from '@/utils/formatters';
import { getDocumentStageLabel, getDocumentStatusLabel } from '@/utils/knowledgeStatus';

import './DocumentList.css';

interface DocumentListProps {
  documents: Document[];
  onDelete?: () => void;
}

export const DocumentList = ({ documents, onDelete }: DocumentListProps) => {
  const handleDelete = async (documentId: string) => {
    try {
      await knowledgeService.deleteDocument(documentId);
      message.success('文档删除成功');
      await onDelete?.();
    } catch (error: any) {
      message.error(error.message || '文档删除失败');
    }
  };

  const columns: ColumnsType<Document> = [
    {
      title: '文档名称',
      dataIndex: 'fileName',
      key: 'fileName',
      render: (_, record) => (
        <Space>
          <FileTextOutlined />
          {record.fileName || record.filename || '-'}
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'fileType',
      key: 'fileType',
      width: 100,
      responsive: ['md'],
    },
    {
      title: '大小',
      dataIndex: 'fileSize',
      key: 'fileSize',
      width: 120,
      responsive: ['md'],
      render: (size) => formatFileSize(size || 0),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status, record) => {
        const currentStatus = status || 'completed';
        const colorMap: Record<string, string> = {
          pending: 'default',
          processing: 'processing',
          completed: 'success',
          failed: 'error',
        };

        return (
          <Space wrap size={4}>
            <Tag color={colorMap[currentStatus] || 'default'}>{getDocumentStatusLabel(currentStatus)}</Tag>
            {record.canRetryVectorization ? (
              <Tag color="orange" icon={<SyncOutlined />}>
                待补向量 {record.missingVectorChunkCount ?? 0}
              </Tag>
            ) : null}
          </Space>
        );
      },
    },
    {
      title: '处理进度',
      key: 'progress',
      width: 240,
      render: (_, record) => {
        const currentStatus = record.status || 'completed';
        const progress = record.processingProgress ?? (currentStatus === 'completed' ? 100 : 0);
        const stageLabel = getDocumentStageLabel(record.processingStage);

        if (currentStatus === 'completed' && !record.processingStage) {
          return <Typography.Text type="success">处理完成</Typography.Text>;
        }

        return (
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            <Progress
              percent={progress}
              size="small"
              status={currentStatus === 'failed' ? 'exception' : currentStatus === 'completed' ? 'success' : 'active'}
            />
            <Typography.Text type={currentStatus === 'failed' ? 'danger' : 'secondary'}>
              {currentStatus === 'failed' ? record.errorMessage || '处理失败' : stageLabel || '处理中'}
            </Typography.Text>
            {record.chunkCount > 0 ? (
              <Typography.Text type="secondary">
                向量分块：{record.vectorizedChunkCount ?? 0}/{record.chunkCount}
              </Typography.Text>
            ) : null}
          </Space>
        );
      },
    },
    {
      title: '分块数',
      dataIndex: 'chunkCount',
      key: 'chunkCount',
      width: 100,
      responsive: ['lg'],
    },
    {
      title: '上传时间',
      dataIndex: 'uploadTime',
      key: 'uploadTime',
      width: 180,
      responsive: ['lg'],
      render: (_, record) => formatDate(record.uploadTime || record.createdAt || ''),
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, record) => (
        <Popconfirm title="确认删除这个文档吗？" onConfirm={() => handleDelete(record.documentId)} okText="确认" cancelText="取消">
          <Button type="link" danger icon={<DeleteOutlined />}>
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div className="knowledge-document-list">
      <Table
        columns={columns}
        dataSource={documents}
        rowKey="documentId"
        pagination={{
          pageSize: 10,
          showSizeChanger: true,
          hideOnSinglePage: true,
          pageSizeOptions: [10, 20, 50],
        }}
        scroll={{ x: 'max-content', y: 'calc(100vh - 420px)' }}
        sticky
      />
    </div>
  );
};
