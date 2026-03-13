import { useState } from 'react';
import { Input, Button, Space } from 'antd';
import { SendOutlined, StopOutlined } from '@ant-design/icons';

const { TextArea } = Input;

interface InputBoxProps {
  onSend: (messageText: string, conversationId?: string) => void;
  isStreaming: boolean;
  onStop: () => void;
  currentConversationId?: string;
}

export const InputBox = ({ onSend, isStreaming, onStop, currentConversationId }: InputBoxProps) => {
  const [input, setInput] = useState('');

  const handleSend = () => {
    const trimmedInput = input.trim();
    if (!trimmedInput || isStreaming) {
      return;
    }

    onSend(trimmedInput, currentConversationId);
    setInput('');
    console.log('[InputBox] 已触发发送消息');
  };

  const handleKeyPress = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="small">
      <Space.Compact style={{ width: '100%' }}>
        <TextArea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyPress}
          placeholder="输入消息... (Shift+Enter 换行)"
          autoSize={{ minRows: 1, maxRows: 4 }}
          disabled={isStreaming}
        />
        {isStreaming ? (
          <Button type="primary" danger icon={<StopOutlined />} onClick={onStop}>
            暂停对话
          </Button>
        ) : (
          <Button type="primary" icon={<SendOutlined />} onClick={handleSend} disabled={!input.trim()}>
            发送
          </Button>
        )}
      </Space.Compact>
    </Space>
  );
};
