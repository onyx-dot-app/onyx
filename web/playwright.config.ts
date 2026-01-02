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

  // When debugging, comment out the first `workers` line and uncomment the second one.
  // The second one runs the tests in serial, which helps when using the playwright-debugger to step through each test-step.
  // - @raunakab
  workers: process.env.CI ? 2 : undefined, // Limit to 2 parallel workers in CI to reduce flakiness
  // workers: 1,

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
  outputDir: "test-results",
  use: {
    // Base URL for the application, can be overridden via BASE_URL environment variable
    baseURL: process.env.BASE_URL || "http://localhost:3000",
    // Capture trace on failure
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "admin",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 720 },
        storageState: "admin_auth.json",
      },
      grepInvert: /@exclusive/,
    },
    {
      name: "no-auth",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 720 },
      },
      grepInvert: /@exclusive/,
    },
    {
      // this suite runs independently and serially + slower
      // we should be cautious about bloating this suite
      name: "exclusive",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 720 },
        storageState: "admin_auth.json",
      },
      grep: /@exclusive/,
      workers: 1,
    },
  ],
});
