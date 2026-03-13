import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import LoginPage from './pages/LoginPage';
import ChatPage from './pages/ChatPage';
import KnowledgePage from './pages/KnowledgePage';
import ToolsPage from './pages/ToolsPage';
import MCPPage from './pages/MCPPage';
import ContentGenerationPage from './pages/ContentGenerationPage';
import { useAuth } from './hooks/useAuth';
import { ErrorBoundary } from './components/common/ErrorBoundary';
import { Loading } from './components/common/Loading';
import './styles/global.css';

const PrivateRoute = ({ children }: { children: React.ReactNode }) => {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return <Loading />;
  }

  return isAuthenticated ? <>{children}</> : <Navigate to="/login" />;
};

function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <ErrorBoundary>
        <BrowserRouter
          future={{
            v7_startTransition: true,
            v7_relativeSplatPath: true,
          }}
        >
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/"
              element={
                <PrivateRoute>
                  <ChatPage />
                </PrivateRoute>
              }
            />
            <Route
              path="/knowledge"
              element={
                <PrivateRoute>
                  <KnowledgePage />
                </PrivateRoute>
              }
            />
            <Route
              path="/tools"
              element={
                <PrivateRoute>
                  <ToolsPage />
                </PrivateRoute>
              }
            />
            <Route
              path="/mcp"
              element={
                <PrivateRoute>
                  <MCPPage />
                </PrivateRoute>
              }
            />
            <Route
              path="/content-generation"
              element={
                <PrivateRoute>
                  <ContentGenerationPage />
                </PrivateRoute>
              }
            />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </BrowserRouter>
      </ErrorBoundary>
    </ConfigProvider>
  );
}

export default App;
