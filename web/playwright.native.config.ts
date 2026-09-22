import { defineConfig, devices } from "@playwright/test";
import base from "./playwright.config";
export default defineConfig({
  ...base,
  globalSetup: undefined,
  workers: 1,
  projects: [{ name: "native-browser", use: { ...devices["Desktop Chrome"] } }],
  use: {
    ...base.use,
    baseURL: process.env.BASE_URL || "http://localhost:3002",
  },
});
