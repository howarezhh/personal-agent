import { Spin } from 'antd';

export const Loading = () => {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      height: '100vh',
    }}>
      <Spin size="large" tip="加载中...">
        <div style={{ padding: '50px' }} />
      </Spin>
    </div>
  );
};
