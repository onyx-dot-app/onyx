import { defineConfig } from "vite";
import { resolve } from "path";

export default defineConfig(({ mode }) => {
  const isSelfHosted = mode === "self-hosted";

  return {
    resolve: {
      alias: {
        "@": resolve(__dirname, "./src"),
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
          inlineDynamicImports: true,
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
            process.env.VITE_WIDGET_BACKEND_URL,
          ),
          "import.meta.env.VITE_WIDGET_API_KEY": JSON.stringify(
            process.env.VITE_WIDGET_API_KEY,
          ),
        }
      : {},
  };
});
