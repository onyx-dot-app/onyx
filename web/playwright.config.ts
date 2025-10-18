import { defineConfig, devices } from "@playwright/test";
import * as dotenv from "dotenv";

dotenv.config({ path: ".vscode/.env" });

export default defineConfig({
  globalSetup: require.resolve("./tests/e2e/global-setup"),
  timeout: 100000, // 100 seconds timeout
  expect: {
    timeout: 15000, // 15 seconds timeout for all assertions to reduce flakiness
  },
  retries: process.env.CI ? 2 : 0, // Retry failed tests 2 times in CI, 0 locally
  workers: process.env.CI ? 2 : undefined, // Limit to 2 parallel workers in CI to reduce flakiness
  reporter: [
    ["list"],
    // Warning: uncommenting the html reporter may cause the chromatic-archives
    // directory to be deleted after the test run, which will break CI.
    // [
    //   'html',
    //   {
    //     outputFolder: 'test-results', // or whatever directory you want
    //     open: 'never', // can be 'always' | 'on-failure' | 'never'
    //   },
    // ],
  ],
  // Only run Playwright tests from tests/e2e directory (ignore Jest tests in src/)
  testMatch: /.*\/tests\/e2e\/.*\.spec\.ts/,
  projects: [
    {
      name: "admin",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 720 },
        storageState: "admin_auth.json",
      },
    },
    {
      name: "no-auth",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 720 },
      },
    },
  ],
});
