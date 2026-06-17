import { defineConfig } from "tsup";
import { preserveDirectivesPlugin } from "esbuild-plugin-preserve-directives";

// CSS imports in Opal source use the @opal/* path alias (e.g.
// "@opal/components/tooltip/styles.css"). That alias is a dev-only tsconfig
// path that consumers don't have, and the individual CSS files are not
// published — only the bundled dist/styles.css is. Keeping them in the dist
// JS as external imports leaves unresolvable specifiers for every consumer.
// This plugin drops all CSS imports from the JS output; styles are loaded via
// the bundled dist/styles.css (or dist/root.css) that bundle-css.mjs produces.
const dropCssImports = {
  name: "drop-css-imports",
  setup(build: import("esbuild").PluginBuild) {
    build.onResolve({ filter: /\.css$/ }, () => ({
      path: "drop-css",
      namespace: "drop-css-ns",
    }));
    build.onLoad({ filter: /.*/, namespace: "drop-css-ns" }, () => ({
      contents: "",
      loader: "js" as const,
    }));
  },
};

export default defineConfig({
  entry: [
    "src/components/index.ts",
    "src/layouts/index.ts",
    "src/core/index.ts",
    "src/icons/index.ts",
    "src/illustrations/index.ts",
    "src/logos/index.ts",
    "src/time.ts",
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
  ],
  esbuildPlugins: [
    dropCssImports,
    preserveDirectivesPlugin({
      directives: ["use client"],
      include: /\.(jsx?|tsx?)$/,
      exclude: /node_modules/,
    }),
  ],
  esbuildOptions(options) {
    options.jsx = "automatic";
  },
});
