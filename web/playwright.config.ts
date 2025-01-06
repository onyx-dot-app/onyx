import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  workers: 1, // temporary change to see if single threaded testing stabilizes the tests
  testDir: "./tests/e2e", // Folder for test files
  reporter: "list",
  // Configure paths for screenshots
  // expect: {
  //   toMatchSnapshot: {
  //     threshold: 0.2, // Adjust the threshold for visual diffs
  //   },
  // },
  // reporter: [["html", { outputFolder: "test-results/output/report" }]], // HTML report location
  // outputDir: "test-results/output/screenshots", // Set output folder for test artifacts
  projects: [
    {
      // dependency for admin workflows
      name: "admin_setup",
      testMatch: /.*\admin_auth\.setup\.ts/,
    },
    {
      // tests admin workflows
      name: "chromium-admin",
      grep: /@admin/,
      use: {
        ...devices["Desktop Chrome"],
        // Use prepared auth state.
        storageState: "admin_auth.json",
      },
      dependencies: ["admin_setup"],
    },
    {
      // tests logged out / guest workflows
      name: "chromium-guest",
      grep: /@guest/,
      use: {
        ...devices["Desktop Chrome"],
      },
    },
  ],
});
