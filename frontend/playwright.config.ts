import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright 浏览器端回归配置。
 * 目标：只覆盖前端真实交互主链路，不引入额外后端启动耦合。
 */
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: 'line',
  outputDir: './tests/.playwright-artifacts',
  use: {
    baseURL: 'http://127.0.0.1:3000',
    headless: true,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
  projects: [
    {
      name: 'msedge',
      use: {
        ...devices['Desktop Chrome'],
        channel: 'msedge',
      },
    },
  ],
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 3000',
    url: 'http://127.0.0.1:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
