import { MessageOutlined } from '@ant-design/icons';
import { Card, Space, Typography } from 'antd';

import type { ConversationSummary } from '@/types';
import { formatRelativeTime } from '@/utils/formatters';

import './ConversationItem.css';

const { Text } = Typography;

interface ConversationItemProps {
  conversation: ConversationSummary;
  isActive: boolean;
  onClick: () => void;
}

export const ConversationItem = ({ conversation, isActive, onClick }: ConversationItemProps) => (
  <Card className={`conversation-item ${isActive ? 'active' : ''}`} onClick={onClick} hoverable size="small" style={{ marginBottom: 8 }}>
    <Space direction="vertical" size="small" style={{ width: '100%' }}>
      <Text strong ellipsis>{conversation.title}</Text>
      {conversation.lastMessagePreview && (
        <Text type="secondary" ellipsis style={{ fontSize: 12 }}>{conversation.lastMessagePreview}</Text>
      )}
      <Space size="small">
        <MessageOutlined style={{ fontSize: 12 }} />
        <Text type="secondary" style={{ fontSize: 12 }}>{conversation.messageCount}</Text>
        <Text type="secondary" style={{ fontSize: 12 }}>{formatRelativeTime(conversation.updatedAt)}</Text>
      </Space>
    </Space>
  </Card>
);

