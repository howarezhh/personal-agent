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
      label: '对话',
    },
    {
      key: '/knowledge',
      icon: <DatabaseOutlined />,
      label: '知识库',
    },
    {
      key: '/tools',
      icon: <ToolOutlined />,
      label: '工具',
    },
    {
      key: '/content-generation',
      icon: <EditOutlined />,
      label: '内容生成',
    },
    {
      key: '/mcp',
      icon: <ApiOutlined />,
      label: 'MCP服务',
    },
  ];

  const userMenuItems: MenuProps['items'] = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: '个人信息',
    },
    {
      type: 'divider',
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      onClick: logout,
    },
  ];

  return (
    <AntHeader style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: '#fff', borderBottom: '1px solid #f0f0f0' }}>
      <Space size="large">
        <Text strong style={{ fontSize: 18 }}>Personal Agent</Text>
        <Menu
          mode="horizontal"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ border: 'none', flex: 1 }}
        />
      </Space>
      <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
        <Space style={{ cursor: 'pointer' }}>
          <Avatar icon={<UserOutlined />} />
          <Text>{user?.username || '用户'}</Text>
        </Space>
      </Dropdown>
    </AntHeader>
  );
};
