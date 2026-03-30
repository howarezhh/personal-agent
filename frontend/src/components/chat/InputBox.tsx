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
    console.log('[InputBox] submitted');
  };

  const handleKeyPress = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  return (
    <Space direction="vertical" className="chat-input-box" style={{ width: '100%' }} size="small">
      <Space.Compact className="chat-input-compact" style={{ width: '100%' }}>
        <TextArea
          className="chat-input-textarea"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyPress}
          placeholder={'\u8f93\u5165\u6d88\u606f...\uff08Shift + Enter \u6362\u884c\uff09'}
          autoSize={{ minRows: 2, maxRows: 6 }}
          disabled={isStreaming}
        />
        {isStreaming ? (
          <Button className="chat-action-button" type="primary" danger icon={<StopOutlined />} onClick={onStop}>
            {'\u505c\u6b62\u56de\u7b54'}
          </Button>
        ) : (
          <Button className="chat-action-button" type="primary" icon={<SendOutlined />} onClick={handleSend} disabled={!input.trim()}>
            {'\u53d1\u9001'}
          </Button>
        )}
      </Space.Compact>
    </Space>
  );
};
