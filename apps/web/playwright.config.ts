import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:5187',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop-chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'tablet-chromium', use: { ...devices['iPad (gen 7)'] } },
  ],
  webServer: [
    {
      command: '.venv/bin/python -m uvicorn services.solver.api:app --host 127.0.0.1 --port 8000',
      cwd: '../..',
      url: 'http://127.0.0.1:8000/api/health',
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5187',
      cwd: '.',
      url: 'http://127.0.0.1:5187',
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
