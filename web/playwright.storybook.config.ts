import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  timeout: 60_000,
  reporter: "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:6019",
    trace: "retain-on-failure",
  },
  // Keep traces outside Vite's watched web root to avoid reloads during tests.
  outputDir: "../test-results/storybook-playwright",
  webServer: {
    command: "bun run storybook --host 127.0.0.1 --port 6019 --ci --no-open",
    url: "http://127.0.0.1:6019",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
