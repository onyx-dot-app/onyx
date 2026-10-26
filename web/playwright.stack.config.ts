import { defineConfig, devices } from "@playwright/test";

if (!process.env.BASE_URL) {
  throw new Error("Set BASE_URL to the disposable stack's frontend URL.");
}
const target = new URL(process.env.BASE_URL);
if (
  target.protocol !== "http:" ||
  !["localhost", "127.0.0.1", "[::1]"].includes(target.hostname)
) {
  throw new Error("Dev-stack smoke tests require a local HTTP deployment.");
}

export default defineConfig({
  globalSetup: "./tests/e2e/stack.setup.ts",
  testDir: "./tests/e2e",
  testMatch: [
    "auth/login.spec.ts",
    "auth/signup.spec.ts",
    "chat/welcome_page.spec.ts",
    "chat/dev_stack.spec.ts",
  ],
  timeout: 120_000,
  expect: { timeout: 30_000 },
  workers: 1,
  retries: 0,
  reporter: "list",
  outputDir: "output/stack-playwright",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.BASE_URL,
    trace: "retain-on-failure",
  },
});
