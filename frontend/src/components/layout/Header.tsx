import { Layout, Menu, Avatar, Dropdown, Space, Typography } from 'antd';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  MessageOutlined,
  DatabaseOutlined,
  UserOutlined,
  LogoutOutlined,
  ToolOutlined,
  EditOutlined,
  ApiOutlined,
} from '@ant-design/icons';
import { useAuth } from '@/hooks/useAuth';
import type { MenuProps } from 'antd';

const { Header: AntHeader } = Layout;
const { Text } = Typography;

export const Header = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();

  const menuItems = [
    {
      key: '/',
      icon: <MessageOutlined />,
      label: '\u5bf9\u8bdd',
    },
    {
      key: '/knowledge',
      icon: <DatabaseOutlined />,
      label: '\u77e5\u8bc6\u5e93',
    },
    {
      key: '/tools',
      icon: <ToolOutlined />,
      label: '\u5de5\u5177',
    },
    {
      key: '/content-generation',
      icon: <EditOutlined />,
      label: '\u5185\u5bb9\u751f\u6210',
    },
    {
      key: '/mcp',
      icon: <ApiOutlined />,
      label: 'MCP\u670d\u52a1',
    },
  ];

  const userMenuItems: MenuProps['items'] = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: '\u4e2a\u4eba\u4fe1\u606f',
    },
    {
      type: 'divider',
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '\u9000\u51fa\u767b\u5f55',
      onClick: logout,
    },
  ];

  return (
    <AntHeader
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
        paddingInline: 16,
        background: '#fff',
        borderBottom: '1px solid #f0f0f0',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 24, minWidth: 0, flex: 1, overflow: 'hidden' }}>
        <Text strong style={{ fontSize: 18, flexShrink: 0 }}>Personal Agent</Text>
        <Menu
          mode="horizontal"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ border: 'none', minWidth: 0, flex: 1 }}
        />
      </div>
      <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
        <Space style={{ cursor: 'pointer' }}>
          <Avatar icon={<UserOutlined />} />
          <Text>{user?.username || '\u7528\u6237'}</Text>
        </Space>
      </Dropdown>
    </AntHeader>
  );
};
