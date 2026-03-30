import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Layout, Select, Space, Typography } from 'antd';

import { useTaskRuntimeChat } from '@/hooks/useTaskRuntimeChat';
import { knowledgeService } from '@/services/knowledgeService';
import type { KnowledgeBase } from '@/types';

import { ExecutionTimelinePanel } from './ExecutionTimelinePanel';
import { InputBox } from './InputBox';
import { MessageList } from './MessageList';
import { TaskRuntimePlanCard } from './TaskRuntimePlanCard';

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
    runtimeGoal,
    runtimePlan,
    runtimeTaskStatus,
    citations,
    error,
    selectedKnowledgeBaseId,
    sendMessage,
    pauseTask,
    resumeTask,
    cancelTask,
    retryTask,
    taskActionLoading,
    stopStreaming,
    setSelectedKnowledgeBaseId,
  } = useTaskRuntimeChat();

  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const contentRef = useRef<HTMLDivElement>(null);
  const hasMessages = messages.length > 0
    || Boolean(streamingContent)
    || thinkingSteps.length > 0
    || Object.keys(workflowTrace).length > 0
    || Boolean(runtimeGoal)
    || Boolean(runtimePlan)
    || Boolean(runtimeTaskStatus);
  const checkpointGraphName = useMemo(
    () => workflowTrace.checkpointGraphName,
    [workflowTrace.checkpointGraphName]
  );
  const checkpointThreadId = useMemo(
    () => workflowTrace.checkpointThreadId || null,
    [workflowTrace.checkpointThreadId]
  );

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
        {hasMessages ? (
          <>
            <MessageList messages={messages} streamingContent={streamingContent} streamingCitations={citations} />
            <TaskRuntimePlanCard
              goal={runtimeGoal}
              plan={runtimePlan}
              taskStatus={runtimeTaskStatus}
              actionLoading={taskActionLoading}
              onPause={() => void pauseTask()}
              onResume={() => void resumeTask()}
              onCancel={() => void cancelTask()}
              onRetry={() => void retryTask()}
            />
            <ExecutionTimelinePanel
              steps={thinkingSteps}
              trace={workflowTrace}
              status={streamStatus}
              isStreaming={isStreaming}
              checkpointGraphName={checkpointGraphName}
              checkpointThreadId={checkpointThreadId}
            />
          </>
        ) : (
          <div className="chat-empty-state">
            <div className="chat-empty-badge">{'AI 助手'}</div>
            <h2 className="chat-empty-title">{'开始一段新的对话'}</h2>
            <p className="chat-empty-description">
              {'你可以直接提问、总结资料、生成内容，或者结合知识库进行更精准的回答。'}
            </p>
            <div className="chat-empty-suggestions">
              <span className="chat-empty-chip">{'总结一篇文档的重点'}</span>
              <span className="chat-empty-chip">{'帮我写一份汇报提纲'}</span>
              <span className="chat-empty-chip">{'基于知识库回答问题'}</span>
            </div>
          </div>
        )}
      </Content>
      <Footer className="chat-footer">
        <div className="chat-footer-inner">
          <div className="chat-tools-row">
            <Space size={8} wrap>
              <Text className="chat-tools-label">{'知识库选择'}</Text>
              <Select
                allowClear
                placeholder={'不使用知识库'}
                className="chat-knowledge-select"
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
        </div>
      </Footer>
    </Layout>
  );
};
