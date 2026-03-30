import { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useAuth } from './hooks/useAuth';
import { ErrorBoundary } from './components/common/ErrorBoundary';
import { Loading } from './components/common/Loading';
import './styles/global.css';

const LoginPage = lazy(() => import('./pages/LoginPage'));
const ChatPage = lazy(() => import('./pages/ChatPage'));
const KnowledgePage = lazy(() => import('./pages/KnowledgePage'));
const ToolsPage = lazy(() => import('./pages/ToolsPage'));
const MCPPage = lazy(() => import('./pages/MCPPage'));
const ContentGenerationPage = lazy(() => import('./pages/ContentGenerationPage'));

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
          <Suspense fallback={<Loading />}>
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
          </Suspense>
        </BrowserRouter>
      </ErrorBoundary>
    </ConfigProvider>
  );
}

export default App;
