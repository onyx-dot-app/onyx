import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  globalSetup: require.resolve("./tests/e2e/global-setup"),
  timeout: 30000, // 30 seconds timeout
  projects: [
    {
      name: "admin",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 720 },
        storageState: "admin_auth.json",
      },
      testIgnore: ["**/codeUtils.test.ts"],
    },
  ],
});
