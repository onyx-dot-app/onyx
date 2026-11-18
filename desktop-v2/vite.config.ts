import { fileURLToPath } from "node:url";
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, type Plugin } from "vite";

const root = path.dirname(fileURLToPath(import.meta.url));
const opalSrc = path.resolve(root, "../web/lib/opal/src");
const DEV_PORT = 1420;

// Local windows only talk to Rust over IPC; no page may reach the network directly.
function cspMetaPlugin(): Plugin {
  return {
    name: "onyx-desktop-csp",
    transformIndexHtml(_html, ctx) {
      const isDev = Boolean(ctx.server);
      const connect = ["'self'", "ipc:", "http://ipc.localhost"];
      if (isDev) connect.push(`ws://localhost:${DEV_PORT}`);
      const policy = [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self' data:",
        `connect-src ${connect.join(" ")}`,
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-src 'none'",
      ].join("; ");
      return [
        {
          tag: "meta",
          attrs: { "http-equiv": "Content-Security-Policy", content: policy },
          injectTo: "head-prepend",
        },
      ];
    },
  };
}

export default defineConfig({
  plugins: [cspMetaPlugin(), tailwindcss()],
  clearScreen: false,
  resolve: {
    alias: [
      { find: /^@opal\/(.*)$/, replacement: `${opalSrc}/$1` },
      { find: /^@\/(.*)$/, replacement: `${path.resolve(root, "src")}/$1` },
      {
        find: /^@radix-ui\/react-tooltip$/,
        replacement: path.resolve(root, "../web/node_modules/@radix-ui/react-tooltip"),
      },
      { find: /^next\/link$/, replacement: path.resolve(root, "src/shims/next-link.tsx") },
      {
        find: /^next\/navigation$/,
        replacement: path.resolve(root, "src/shims/next-navigation.ts"),
      },
    ],
    dedupe: ["react", "react-dom"],
  },
  server: {
    port: DEV_PORT,
    strictPort: true,
    fs: { allow: [root, path.resolve(root, "../web")] },
  },
  build: {
    outDir: "dist",
    target: "safari16",
    rollupOptions: {
      // Radix ships "use client" directives for Next.js; they mean nothing here.
      onwarn(warning, warn) {
        if (warning.code === "MODULE_LEVEL_DIRECTIVE") return;
        warn(warning);
      },
      input: {
        onboarding: path.resolve(root, "onboarding.html"),
        login: path.resolve(root, "login.html"),
        launcher: path.resolve(root, "launcher.html"),
        preferences: path.resolve(root, "preferences.html"),
      },
    },
  },
});
