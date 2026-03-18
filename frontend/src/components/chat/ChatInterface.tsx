import { useEffect, useRef, useState } from 'react';
import { Alert, Layout, Select, Space, Typography } from 'antd';

import { useChat } from '@/hooks/useChat';
import { knowledgeService } from '@/services/knowledgeService';
import type { KnowledgeBase } from '@/types';

import { CitationList } from './CitationList';
import { ExecutionTimelinePanel } from './ExecutionTimelinePanel';
import { InputBox } from './InputBox';
import { MessageList } from './MessageList';

import './ChatInterface.css';

const { Content, Footer } = Layout;
const { Text } = Typography;

export const ChatInterface = () => {
  const {
    messages,
    currentConversationId,
    isStreaming,
    streamStatus,
    streamingContent,
    thinkingSteps,
    workflowTrace,
    citations,
    error,
    selectedKnowledgeBaseId,
    sendMessage,
    stopStreaming,
    setSelectedKnowledgeBaseId,
  } = useChat();

  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight;
    }
  }, [messages, streamingContent]);

  useEffect(() => {
    const loadKnowledgeBases = async () => {
      try {
        const response = await knowledgeService.getKnowledgeBases();
        setKnowledgeBases(response.knowledgeBases);
        if (
          selectedKnowledgeBaseId &&
          !response.knowledgeBases.some((item) => item.knowledgeBaseId === selectedKnowledgeBaseId)
        ) {
          setSelectedKnowledgeBaseId(null);
        }
      } catch {
        setKnowledgeBases([]);
      }
    };

    void loadKnowledgeBases();
  }, [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId]);

  return (
    <Layout className="chat-interface">
      <Content className="chat-messages" ref={contentRef}>
        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
        <MessageList messages={messages} streamingContent={streamingContent} />
        <ExecutionTimelinePanel steps={thinkingSteps} trace={workflowTrace} status={streamStatus} isStreaming={isStreaming} />
        {citations.length > 0 && <CitationList citations={citations} />}
      </Content>
      <Footer className="chat-footer">
        <div className="chat-tools-row">
          <Space size={8} wrap>
            <Text className="chat-tools-label">知识库选择</Text>
            <Select
              allowClear
              placeholder="不使用知识库"
              style={{ minWidth: 240 }}
              value={selectedKnowledgeBaseId || undefined}
              onChange={(value) => setSelectedKnowledgeBaseId(value || null)}
              options={knowledgeBases.map((item) => ({
                label: item.isDefault ? `${item.name}（默认）` : item.name,
                value: item.knowledgeBaseId,
              }))}
            />
          </Space>
        </div>
        <InputBox onSend={sendMessage} isStreaming={isStreaming} onStop={stopStreaming} currentConversationId={currentConversationId || undefined} />
      </Footer>
    </Layout>
  );
};
