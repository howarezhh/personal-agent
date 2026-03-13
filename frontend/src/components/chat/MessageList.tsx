import { Space } from 'antd';

import type { Message } from '@/types';

import { MessageItem } from './MessageItem';

interface MessageListProps {
  messages: Message[];
  streamingContent?: string;
}

export const MessageList = ({ messages, streamingContent }: MessageListProps) => (
  <Space direction="vertical" size="large" style={{ width: '100%' }}>
    {messages.map((message, index) => (
      <MessageItem key={message.messageId || `message-${index}`} message={message} />
    ))}
    {streamingContent && (
      <MessageItem
        key="streaming-message"
        message={{
          messageId: 'streaming',
          conversationId: '',
          messageType: 'assistant',
          content: streamingContent,
          sequenceNumber: 0,
          createdAt: new Date().toISOString(),
        }}
        isStreaming
      />
    )}
  </Space>
);

