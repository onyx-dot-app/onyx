import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  test: {
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    environment: "jsdom",
    setupFiles: ["src/test-setup.ts"],
  },
  resolve: {
    alias: {
      "@onyx/genui": path.resolve(__dirname, "../core/src"),
    },
  },
});
