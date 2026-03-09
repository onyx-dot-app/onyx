import type { StorybookConfig } from "@storybook/react-vite";
import path from "path";

const config: StorybookConfig = {
  stories: [
    "./*.mdx",
    "../lib/opal/src/**/*.stories.@(ts|tsx)",
    "../src/refresh-components/**/*.stories.@(ts|tsx)",
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
    reactDocgen: "react-docgen",
  },
  viteFinal: async (config) => {
    config.resolve = config.resolve ?? {};
    config.resolve.alias = {
      ...config.resolve.alias,
      "@": path.resolve(__dirname, "../src"),
      "@opal": path.resolve(__dirname, "../lib/opal/src"),
      "@public": path.resolve(__dirname, "../public"),
      // Next.js module stubs for Vite
      "next/link": path.resolve(__dirname, "mocks/next-link.tsx"),
      "next/navigation": path.resolve(__dirname, "mocks/next-navigation.tsx"),
      "next/image": path.resolve(__dirname, "mocks/next-image.tsx"),
    };

    // Process CSS with Tailwind via PostCSS
    config.css = config.css ?? {};
    config.css.postcss = path.resolve(__dirname, "..");

    return config;
  },
};

export default config;
