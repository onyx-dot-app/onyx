import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  globalSetup: require.resolve("./tests/e2e/global-setup"),
  timeout: 60000, // 60 seconds timeout
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
  projects: [
    {
      name: "admin",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 720 },
        storageState: "admin_auth.json",
      },
      testIgnore: ["**/codeUtils.test.ts", "**/chat/**/*.spec.ts"],
    },
  ],
});
