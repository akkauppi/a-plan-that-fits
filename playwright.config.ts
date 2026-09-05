import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/browser', timeout: 240000, expect: { timeout: 40000 },
  fullyParallel: false, workers: 1, retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: 'http://127.0.0.1:5187/tour/', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    { name: 'desktop-chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } },
    { name: 'tablet-chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 820, height: 1180 }, hasTouch: true } },
  ],
  webServer: { command: 'node tools/serve.mjs', url: 'http://127.0.0.1:5187/tour/', reuseExistingServer: false, timeout: 30000 },
})
