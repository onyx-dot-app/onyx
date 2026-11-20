import { defineConfig, loadEnv } from "vite";
import { resolve } from "path";

export default defineConfig(({ mode }) => {
  const isSelfHosted = mode === "self-hosted";

  // Load env file based on mode
  const env = loadEnv(mode, process.cwd(), "");

  return {
    resolve: {
      alias: {
        "@": resolve(__dirname, "./src"),
        "@onyx-acp": resolve(__dirname, "../web/lib/shared/src/contracts/acp.ts"),
      },
    },
    build: {
      lib: {
        entry: resolve(__dirname, "src/index.ts"),
        name: "OnyxWidget",
        fileName: "onyx-widget",
        formats: ["es"],
      },
      rollupOptions: {
        output: {
          codeSplitting: false,
        },
      },
      sourcemap: false,
      minify: "terser",
      terserOptions: {
        compress: {
          drop_console: true,
        },
      },
    },
    define: isSelfHosted
      ? {
          "import.meta.env.VITE_WIDGET_BACKEND_URL": JSON.stringify(
            env.VITE_WIDGET_BACKEND_URL
          ),
          "import.meta.env.VITE_WIDGET_API_KEY": JSON.stringify(
            env.VITE_WIDGET_API_KEY
          ),
        }
      : {},
  };
});
