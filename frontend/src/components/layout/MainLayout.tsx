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
      <Content style={{ height: 'calc(100vh - 64px)' }}>
        {children}
      </Content>
    </Layout>
  );
};
