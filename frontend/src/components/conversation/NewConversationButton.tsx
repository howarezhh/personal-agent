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
      console.error('[NewConversationButton] create conversation failed:', error);
    }
  };

  return (
    <Button
      type="primary"
      icon={<PlusOutlined />}
      onClick={handleNewConversation}
      block
    >
      {'\u65b0\u5efa\u5bf9\u8bdd'}
    </Button>
  );
};
