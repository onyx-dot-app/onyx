import type { StorybookConfig } from "@storybook/react-vite";
import path from "path";
import { fileURLToPath } from "url";

// Node 24 type-strips this file as ESM (no `__dirname`); older toolchains
// transpile it to CJS (no `import.meta.url` shim), so support both.
const dirname =
  typeof __dirname !== "undefined"
    ? __dirname
    : path.dirname(fileURLToPath(import.meta.url));

const config: StorybookConfig = {
  stories: [
    "./*.mdx",
    "../lib/opal/src/**/*.stories.@(ts|tsx)",
    "../src/refresh-components/**/*.stories.@(ts|tsx)",
    "../src/sections/**/*.stories.@(ts|tsx)",
    "../src/app/craft/**/*.stories.@(ts|tsx)",
  ],
  addons: ["@storybook/addon-essentials", "@storybook/addon-themes"],
  framework: {
    name: "@storybook/react-vite",
    options: {},
  },
  staticDirs: ["../public"],
  docs: {
    autodocs: "tag",
  },
  typescript: {
    reactDocgen: "react-docgen-typescript",
  },
  viteFinal: async (config) => {
    config.resolve = config.resolve ?? {};
    config.resolve.alias = {
      ...config.resolve.alias,
      "@": path.resolve(dirname, "../src"),
      "@opal": path.resolve(dirname, "../lib/opal/src"),
      "@public": path.resolve(dirname, "../public"),
      // Next.js module stubs for Vite
      "next/link": path.resolve(dirname, "mocks/next-link.tsx"),
      "next/navigation": path.resolve(dirname, "mocks/next-navigation.tsx"),
      "next/image": path.resolve(dirname, "mocks/next-image.tsx"),
    };

    // Process CSS with Tailwind via PostCSS
    config.css = config.css ?? {};
    config.css.postcss = path.resolve(dirname, "..");

    // Provide `process.env` for modules that reference it at the top level
    // (e.g. src/lib/constants.ts). Vite doesn't polyfill Node globals.
    config.define = {
      ...config.define,
      "process.env": JSON.stringify({}),
    };

    return config;
  },
};

export default config;
