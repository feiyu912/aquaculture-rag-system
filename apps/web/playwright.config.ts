import { defineConfig, devices } from "@playwright/test";

const WEB_BASE = process.env.AQUA_WEB_BASE ?? "http://127.0.0.1:3001";
const API_BASE = process.env.AQUA_API_BASE ?? "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: ".review/e2e-report" }]],
  use: {
    baseURL: WEB_BASE,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    actionTimeout: 20_000,
    navigationTimeout: 45_000,
  },
  projects: [
    {
      name: "desktop-chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
      testIgnore: /.*\.mobile\.spec\.ts/,
    },
    {
      name: "mobile-chromium",
      use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 } },
      testMatch: /.*\.mobile\.spec\.ts/,
    },
  ],
  metadata: { apiBase: API_BASE },
});
