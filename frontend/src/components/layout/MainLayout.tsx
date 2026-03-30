import { Layout } from 'antd';
import { Header } from './Header';

const { Content } = Layout;

interface MainLayoutProps {
  children: React.ReactNode;
}

export const MainLayout = ({ children }: MainLayoutProps) => {
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header />
      {/* 主内容区改为弹性布局，避免使用固定视口高度导致页面被裁切 */}
      <Content className="app-layout__content">
        {children}
      </Content>
    </Layout>
  );
};
