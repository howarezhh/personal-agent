import { DeleteOutlined, FileTextOutlined } from '@ant-design/icons';
import { Button, message, Popconfirm, Space, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';

import { knowledgeService } from '@/services/knowledgeService';
import type { Document } from '@/types';
import { formatDate, formatFileSize } from '@/utils/formatters';

interface DocumentListProps {
  documents: Document[];
  onDelete?: () => void;
}

export const DocumentList = ({ documents, onDelete }: DocumentListProps) => {
  const handleDelete = async (documentId: string) => {
    try {
      await knowledgeService.deleteDocument(documentId);
      message.success('文档删除成功');
      onDelete?.();
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
    { title: '类型', dataIndex: 'fileType', key: 'fileType', width: 100 },
    {
      title: '大小',
      dataIndex: 'fileSize',
      key: 'fileSize',
      width: 120,
      render: (size) => formatFileSize(size || 0),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status) => {
        const currentStatus = status || 'completed';
        const colorMap: Record<string, string> = {
          pending: 'default',
          processing: 'processing',
          completed: 'success',
          failed: 'error',
        };
        return <Tag color={colorMap[currentStatus] || 'default'}>{currentStatus}</Tag>;
      },
    },
    { title: '分块数', dataIndex: 'chunkCount', key: 'chunkCount', width: 100 },
    {
      title: '上传时间',
      dataIndex: 'uploadTime',
      key: 'uploadTime',
      width: 180,
      render: (_, record) => formatDate(record.uploadTime || record.createdAt || ''),
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, record) => (
        <Popconfirm title="确认删除这个文档吗？" onConfirm={() => handleDelete(record.documentId)} okText="确认" cancelText="取消">
          <Button type="link" danger icon={<DeleteOutlined />}>删除</Button>
        </Popconfirm>
      ),
    },
  ];

  return <Table columns={columns} dataSource={documents} rowKey="documentId" pagination={{ pageSize: 10 }} />;
};
