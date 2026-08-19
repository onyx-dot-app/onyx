import type { StorybookConfig } from "@storybook/react-vite";
import path, { dirname } from "path";
import { fileURLToPath } from "url";

// Node 24 type-strips this file as ESM (no `__dirname`); older toolchains
// transpile it to CJS (no `import.meta.url` shim), so support both.
const configDir =
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
    "../src/views/**/*.stories.@(ts|tsx)",
  ],
  addons: [
    getAbsolutePath("@storybook/addon-themes"),
    getAbsolutePath("@storybook/addon-mcp"),
    getAbsolutePath("@storybook/addon-docs"),
  ],
  framework: {
    name: getAbsolutePath("@storybook/react-vite"),
    options: {},
  },
  staticDirs: ["../public"],
  typescript: {
    reactDocgen: "react-docgen-typescript",
  },
  viteFinal: async (config) => {
    config.resolve = config.resolve ?? {};
    config.resolve.alias = {
      ...config.resolve.alias,
      "@": path.resolve(configDir, "../src"),
      "@opal": path.resolve(configDir, "../lib/opal/src"),
      "@public": path.resolve(configDir, "../public"),
      // Next.js module stubs for Vite
      "next/link": path.resolve(configDir, "mocks/next-link.tsx"),
      "next/navigation": path.resolve(configDir, "mocks/next-navigation.tsx"),
      "next/image": path.resolve(configDir, "mocks/next-image.tsx"),
    };

    // Process CSS with Tailwind via PostCSS
    config.css = config.css ?? {};
    config.css.postcss = path.resolve(configDir, "..");

    // Provide `process.env` for modules that reference it at the top level
    // (e.g. src/lib/constants.ts). Vite doesn't polyfill Node globals.
    config.define = {
      ...config.define,
      "process.env": JSON.stringify({}),
    };

    // Vite's default publicDir copy races/collides with Storybook's own
    // `staticDirs` copy of the same `public/` dir (EEXIST): storybookjs/storybook#24627
    config.publicDir = false;

    return config;
  },
};

export default config;

function getAbsolutePath(value: string): any {
  return dirname(fileURLToPath(import.meta.resolve(`${value}/package.json`)));
}
