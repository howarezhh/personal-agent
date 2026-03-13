import { useState } from 'react';
import { Form, Input, Button, Tabs, Card, message } from 'antd';
import { UserOutlined, LockOutlined, MailOutlined } from '@ant-design/icons';
import { useAuth } from '@/hooks/useAuth';
import { LoginRequest, RegisterRequest } from '@/types';
import './LoginPage.css';

const LoginPage = () => {
  const { login, register } = useAuth();
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('login');

  const handleLogin = async (values: LoginRequest) => {
    console.log('[LoginPage] 用户点击登录按钮');
    console.log('[LoginPage] 表单数据:', { ...values, password: '***' });
    try {
      setLoading(true);
      console.log('[LoginPage] 调用login函数');
      await login(values);
      console.log('[LoginPage] 登录成功');
      message.success('登录成功');
    } catch (error: any) {
      console.error('[LoginPage] 登录失败:', error);
      message.error(error.message || '登录失败');
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (values: RegisterRequest) => {
    console.log('[LoginPage] 用户点击注册按钮');
    console.log('[LoginPage] 表单数据:', { ...values, password: '***' });
    try {
      setLoading(true);
      console.log('[LoginPage] 调用register函数');
      await register(values);
      console.log('[LoginPage] 注册成功');
      message.success('注册成功');
    } catch (error: any) {
      console.error('[LoginPage] 注册失败:', error);
      message.error(error.message || '注册失败');
    } finally {
      setLoading(false);
    }
  };

  const tabItems = [
    {
      key: 'login',
      label: '登录',
      children: (
        <Form onFinish={handleLogin} autoComplete="off">
          <Form.Item
            name="usernameOrEmail"
            rules={[{ required: true, message: '请输入用户名或邮箱' }]}
          >
            <Input
              prefix={<UserOutlined />}
              placeholder="用户名或邮箱"
              size="large"
            />
          </Form.Item>
          <Form.Item
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="密码"
              size="large"
            />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              block
              size="large"
            >
              登录
            </Button>
          </Form.Item>
        </Form>
      ),
    },
    {
      key: 'register',
      label: '注册',
      children: (
        <Form onFinish={handleRegister} autoComplete="off">
          <Form.Item
            name="username"
            rules={[
              { required: true, message: '请输入用户名' },
              { min: 3, message: '用户名至少3个字符' },
            ]}
          >
            <Input
              prefix={<UserOutlined />}
              placeholder="用户名"
              size="large"
            />
          </Form.Item>
          <Form.Item
            name="email"
            rules={[
              { required: true, message: '请输入邮箱' },
              { type: 'email', message: '请输入有效的邮箱地址' },
            ]}
          >
            <Input
              prefix={<MailOutlined />}
              placeholder="邮箱"
              size="large"
            />
          </Form.Item>
          <Form.Item
            name="password"
            rules={[
              { required: true, message: '请输入密码' },
              { min: 8, message: '密码至少8个字符' },
            ]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="密码"
              size="large"
            />
          </Form.Item>
          <Form.Item
            name="fullName"
          >
            <Input
              placeholder="姓名（可选）"
              size="large"
            />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              block
              size="large"
            >
              注册
            </Button>
          </Form.Item>
        </Form>
      ),
    },
  ];

  return (
    <div className="login-page">
      <Card className="login-card" title="Personal Agent">
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
      </Card>
    </div>
  );
};

export default LoginPage;
