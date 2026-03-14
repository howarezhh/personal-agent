import { useEffect, useMemo, useRef } from 'react';
import { Layout } from 'antd';
import { useSearchParams } from 'react-router-dom';

import { ChatInterface } from '@/components/chat/ChatInterface';
import { ConversationList } from '@/components/conversation/ConversationList';
import { MainLayout } from '@/components/layout/MainLayout';
import { useChat } from '@/hooks/useChat';
import { useConversation } from '@/hooks/useConversation';

import './ChatPage.css';

const { Sider, Content } = Layout;

const ChatPage = () => {
  const { conversations, loadConversations, createConversation } = useConversation();
  const { currentConversationId, loadMessages, reset } = useChat();
  const [searchParams, setSearchParams] = useSearchParams();
  const pendingConversationRefreshRef = useRef<string | null>(null);
  const loadedConversationIdRef = useRef<string | null>(null);

  const conversationIdFromUrl = searchParams.get('conversationId');
  const availableConversationIds = useMemo(() => new Set(conversations.map((conversation) => conversation.conversationId)), [conversations]);

  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    const targetConversationId = conversationIdFromUrl || currentConversationId;
    if (!targetConversationId) {
      pendingConversationRefreshRef.current = null;
      loadedConversationIdRef.current = null;
      return;
    }

    if (!availableConversationIds.has(targetConversationId)) {
      if (pendingConversationRefreshRef.current !== targetConversationId) {
        pendingConversationRefreshRef.current = targetConversationId;
        void loadConversations();
        return;
      }

      pendingConversationRefreshRef.current = null;
      loadedConversationIdRef.current = null;
      setSearchParams({}, { replace: true });
      reset();
      return;
    }

    pendingConversationRefreshRef.current = null;

    if (!conversationIdFromUrl || conversationIdFromUrl !== targetConversationId) {
      setSearchParams({ conversationId: targetConversationId }, { replace: true });
    }

    if (loadedConversationIdRef.current === targetConversationId) {
      return;
    }

    loadedConversationIdRef.current = targetConversationId;
    void loadMessages(targetConversationId).catch(() => {
      if (loadedConversationIdRef.current === targetConversationId) {
        loadedConversationIdRef.current = null;
      }
    });
  }, [availableConversationIds, conversationIdFromUrl, currentConversationId, loadConversations, loadMessages, reset, setSearchParams]);

  const handleCreateConversation = async () => {
    const conversation = await createConversation({ title: '新对话' });
    reset();
    setSearchParams({ conversationId: conversation.conversationId }, { replace: false });
  };

  return (
    <MainLayout>
      <Layout style={{ height: '100%' }}>
        <Sider width={280} theme="light" className="conversation-sider">
          <ConversationList conversations={conversations} currentConversationId={currentConversationId} onSelect={(conversationId) => setSearchParams({ conversationId }, { replace: false })} onCreate={handleCreateConversation} />
        </Sider>
        <Content className="chat-content">
          <ChatInterface />
        </Content>
      </Layout>
    </MainLayout>
  );
};

export default ChatPage;
