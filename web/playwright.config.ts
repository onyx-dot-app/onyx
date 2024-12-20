import { defineConfig, devices } from "@playwright/test";
import path from "path";

export default defineConfig({
  workers: 1,
  testDir: "./tests/e2e",
  reporter: "list",
  globalSetup: path.join(__dirname, "tests/e2e/global-setup.ts"),
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
      },
    },
  ],
});
