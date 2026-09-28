import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { defineConfig, type Rolldown } from "tsdown";

// rolldown-plugin-dts only auto-detects TypeScript 7.0, so point its tsgo
// generator at the installed compiler binary.
const require = createRequire(import.meta.url);
const typescriptDir = dirname(require.resolve("typescript/package.json"));
// SAFETY: getExePath.js is TypeScript's CommonJS helper with a default export.
const { default: getTsgoPath } = require(
  join(typescriptDir, "lib/getExePath.js")
) as { default: () => string };

// CSS imports in Opal source use the @opal/* path alias (e.g.
// "@opal/components/tooltip/styles.css"). That alias is a dev-only tsconfig
// path that consumers don't have, and the individual CSS files are not
// published — only the bundled dist/styles.css is. Keeping them in the dist
// JS as external imports leaves unresolvable specifiers for every consumer.
// This plugin drops all CSS imports from the JS output; styles are loaded via
// the bundled dist/styles.css (or dist/root.css) that bundle-css.mjs produces.
const DROPPED_CSS_ID = "\0drop-css";
const dropCssImports: Rolldown.Plugin = {
  name: "drop-css-imports",
  resolveId: {
    filter: { id: /\.css$/ },
    handler: () => ({ id: DROPPED_CSS_ID, moduleSideEffects: false }),
  },
  load: (id) => (id === DROPPED_CSS_ID ? "" : null),
};

// Rolldown drops module-level directives when it bundles modules together.
// Re-add "use client" to each JS chunk that contains a client module, so React
// Server Components consumers still see the client boundary.
const clientModules = new Set<string>();
const preserveUseClient: Rolldown.Plugin = {
  name: "preserve-use-client",
  transform: {
    filter: { id: { include: /\.[jt]sx?$/, exclude: /node_modules/ } },
    handler(code, id) {
      if (/^(?:\s|\/\/[^\n]*|\/\*[\s\S]*?\*\/)*["']use client["']/.test(code)) {
        clientModules.add(id);
      }
      return null;
    },
  },
  banner(chunk) {
    const isClient =
      !chunk.fileName.endsWith(".d.ts") &&
      chunk.moduleIds.some((id) => clientModules.has(id));
    return isClient ? '"use client";' : "";
  },
};

export default defineConfig({
  entry: [
    "src/components/index.ts",
    "src/form/index.ts",
    "src/layouts/index.ts",
    "src/core/index.ts",
    "src/icons/index.ts",
    "src/illustrations/index.ts",
    "src/logos/index.ts",
    "src/hooks/index.ts",
    "src/strings.tsx",
    "src/time.ts",
    "src/types.ts",
    "src/utils.ts",
  ],
  format: "esm",
  platform: "browser",
  target: "es2020",
  tsconfig: "./tsconfig.build.json",
  dts: { generator: "tsgo", tsgo: { path: getTsgoPath() } },
  outExtensions: () => ({ js: ".js", dts: ".d.ts" }),
  clean: true,
  sourcemap: true,
  deps: {
    neverBundle: [
      "react",
      "react-dom",
      "next",
      /^next\//,
      /^@radix-ui/,
      /^@dnd-kit/,
      "@tanstack/react-table",
      "formik",
      "react-markdown",
      "remark-gfm",
      "rehype-sanitize",
    ],
  },
  plugins: [dropCssImports, preserveUseClient],
});
