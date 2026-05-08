import { defineConfig } from "tsup";

export default defineConfig({
  entry: [
    "src/components/index.ts",
    "src/layouts/index.ts",
    "src/core/index.ts",
    "src/icons/index.ts",
    "src/illustrations/index.ts",
    "src/types.ts",
    "src/utils.ts",
  ],
  format: ["esm"],
  target: "es2020",
  dts: { resolve: true, tsconfig: "./tsconfig.build.json" },
  tsconfig: "./tsconfig.build.json",
  clean: true,
  sourcemap: true,
  splitting: false,
  external: [
    "react",
    "react-dom",
    "next",
    /^@radix-ui/,
    /^@dnd-kit/,
    "@tanstack/react-table",
    "formik",
    "react-markdown",
    "remark-gfm",
    "rehype-sanitize",
    /\.css$/,
  ],
  banner: {
    js: '"use client";',
  },
  esbuildOptions(options) {
    options.jsx = "automatic";
  },
});
