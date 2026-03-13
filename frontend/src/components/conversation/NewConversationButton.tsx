import { Button } from 'antd';
import { PlusOutlined } from '@ant-design/icons';

interface NewConversationButtonProps {
  onCreate: () => void;
}

export const NewConversationButton = ({ onCreate }: NewConversationButtonProps) => {
  const handleNewConversation = async () => {
    try {
      await onCreate();
    } catch (error) {
      console.error('[NewConversationButton] 新建会话失败:', error);
    }
  };

  return (
    <Button
      type="primary"
      icon={<PlusOutlined />}
      onClick={handleNewConversation}
      block
    >
      新建对话
    </Button>
  );
};
