import { List } from 'antd';

import type { ConversationSummary } from '@/types';

import { ConversationItem } from './ConversationItem';
import { NewConversationButton } from './NewConversationButton';

interface ConversationListProps {
  conversations: ConversationSummary[];
  currentConversationId: string | null;
  onSelect: (conversationId: string) => void;
  onCreate: () => void;
}

export const ConversationList = ({ conversations, currentConversationId, onSelect, onCreate }: ConversationListProps) => (
  <div style={{ padding: '16px' }}>
    <NewConversationButton onCreate={onCreate} />
    <List
      dataSource={conversations}
      renderItem={(conversation) => (
        <ConversationItem
          conversation={conversation}
          isActive={conversation.conversationId === currentConversationId}
          onClick={() => onSelect(conversation.conversationId)}
        />
      )}
      style={{ marginTop: 16 }}
    />
  </div>
);

