import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return undefined;
          }

          if (id.includes('react-syntax-highlighter') || id.includes('react-markdown') || id.includes('remark-gfm')) {
            return 'markdown';
          }

          if (id.includes('axios')) {
            return 'network';
          }

          return undefined;
        },
      },
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        // 开发环境固定走 IPv4，避免 Windows 下 `localhost` 解析到 `::1` 时触发代理连接聚合错误。
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
