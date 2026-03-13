import { Card, List, Typography, Tag } from 'antd';
import { FileTextOutlined } from '@ant-design/icons';
import { Citation } from '@/types';

const { Paragraph } = Typography;

interface CitationListProps {
  citations: Citation[];
}

export const CitationList = ({ citations }: CitationListProps) => {
  if (citations.length === 0) return null;

  return (
    <Card
      title={
        <span>
          <FileTextOutlined style={{ marginRight: 8 }} />
          引用来源
        </span>
      }
      size="small"
      style={{ marginTop: 16 }}
    >
      <List
        dataSource={citations}
        renderItem={(citation, index) => (
          <List.Item>
            <List.Item.Meta
              title={
                <span>
                  <Tag color="blue">[{index + 1}]</Tag>
                  {citation.source}
                </span>
              }
              description={
                <Paragraph ellipsis={{ rows: 2, expandable: true }}>
                  {citation.content}
                </Paragraph>
              }
            />
          </List.Item>
        )}
      />
    </Card>
  );
};
