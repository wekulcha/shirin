import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', fullyParallel: false, workers: 1, timeout: 45000,
  use: { ...devices['iPhone 13'], browserName: 'chromium', trace: 'retain-on-failure' },
  reporter: 'list',
  webServer: process.env.SHIRIN_BUILT_PREVIEW ? undefined : [
    { command: '../.venv/bin/uvicorn app.main:app --app-dir ../backend --port 8083 --no-access-log', url: 'http://localhost:8083/shirin/api/health', reuseExistingServer: true },
    { command: 'npm run dev', url: 'http://localhost:5183/shirin/', reuseExistingServer: true },
    { command: 'npm --prefix ../admin_panel run dev', url: 'http://localhost:5184/shirin/', reuseExistingServer: true },
    { command: 'npm --prefix ../superadmin_panel run dev', url: 'http://localhost:5185/shirin/superadmin/', reuseExistingServer: true },
  ],
});
