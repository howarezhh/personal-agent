import { Card, Avatar, Typography } from 'antd';
import { UserOutlined, RobotOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Message } from '@/types';
import { formatRelativeTime } from '@/utils/formatters';
import './MessageItem.css';

const { Text } = Typography;

interface MessageItemProps {
  message: Message;
  isStreaming?: boolean;
}

export const MessageItem = ({ message, isStreaming }: MessageItemProps) => {
  const isUser = message.messageType === 'user';

  // Markdown 组件配置 - 不使用 useMemo，确保每次都能正确渲染
  const markdownComponents = {
    // 代码块渲染
    code({ inline, className, children, ...props }: any) {
      const match = /language-(\w+)/.exec(className || '');
      const language = match ? match[1] : '';

      return !inline && language ? (
        <SyntaxHighlighter
          style={vscDarkPlus}
          language={language}
          PreTag="div"
          {...props}
        >
          {String(children).replace(/\n$/, '')}
        </SyntaxHighlighter>
      ) : (
        <code className={className} {...props}>
          {children}
        </code>
      );
    },
    // 段落渲染 - 保持正常间距
    p: ({ children, ...props }: any) => (
      <p style={{ marginBottom: '1em', lineHeight: '1.6' }} {...props}>
        {children}
      </p>
    ),
    // 标题渲染
    h1: ({ children, ...props }: any) => (
      <h1 style={{ marginTop: '1em', marginBottom: '0.5em', fontSize: '1.8em', fontWeight: 'bold' }} {...props}>
        {children}
      </h1>
    ),
    h2: ({ children, ...props }: any) => (
      <h2 style={{ marginTop: '0.8em', marginBottom: '0.4em', fontSize: '1.5em', fontWeight: 'bold' }} {...props}>
        {children}
      </h2>
    ),
    h3: ({ children, ...props }: any) => (
      <h3 style={{ marginTop: '0.6em', marginBottom: '0.3em', fontSize: '1.3em', fontWeight: 'bold' }} {...props}>
        {children}
      </h3>
    ),
    // 列表渲染
    ul: ({ children, ...props }: any) => (
      <ul style={{ marginBottom: '1em', paddingLeft: '2em' }} {...props}>{children}</ul>
    ),
    ol: ({ children, ...props }: any) => (
      <ol style={{ marginBottom: '1em', paddingLeft: '2em' }} {...props}>{children}</ol>
    ),
    li: ({ children, ...props }: any) => (
      <li style={{ marginBottom: '0.3em' }} {...props}>{children}</li>
    ),
    // 引用块渲染
    blockquote: ({ children, ...props }: any) => (
      <blockquote
        style={{
          borderLeft: '4px solid #ddd',
          paddingLeft: '1em',
          marginLeft: 0,
          marginBottom: '1em',
          color: '#666',
        }}
        {...props}
      >
        {children}
      </blockquote>
    ),
    // 表格渲染
    table: ({ children, ...props }: any) => (
      <div style={{ overflowX: 'auto', marginBottom: '1em' }}>
        <table
          style={{
            borderCollapse: 'collapse',
            width: '100%',
            border: '1px solid #ddd',
          }}
          {...props}
        >
          {children}
        </table>
      </div>
    ),
    th: ({ children, ...props }: any) => (
      <th
        style={{
          border: '1px solid #ddd',
          padding: '8px',
          backgroundColor: '#f5f5f5',
          fontWeight: 'bold',
          textAlign: 'left',
        }}
        {...props}
      >
        {children}
      </th>
    ),
    td: ({ children, ...props }: any) => (
      <td
        style={{
          border: '1px solid #ddd',
          padding: '8px',
        }}
        {...props}
      >
        {children}
      </td>
    ),
    // 水平线
    hr: (props: any) => (
      <hr style={{ margin: '1em 0', border: 'none', borderTop: '1px solid #ddd' }} {...props} />
    ),
  };

  return (
    <div className={`message-item ${isUser ? 'message-user' : 'message-assistant'}`}>
      <Card
        className="message-card"
        variant="borderless"
      >
        <div className="message-header">
          <Avatar
            icon={isUser ? <UserOutlined /> : <RobotOutlined />}
            style={{ backgroundColor: isUser ? '#1890ff' : '#52c41a' }}
          />
          <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
            {formatRelativeTime(message.createdAt)}
          </Text>
        </div>
        <div className="message-content">
          {isUser ? (
            <Text style={{ whiteSpace: 'pre-wrap' }}>{message.content}</Text>
          ) : (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={markdownComponents}
            >
              {message.content}
            </ReactMarkdown>
          )}
          {isStreaming && <span className="streaming-cursor">▊</span>}
        </div>
      </Card>
    </div>
  );
};
