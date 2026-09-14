import type { KnipConfig } from "knip";

/**
 * Dead code gate. Zero tolerance: every rule is an error and there is no
 * baseline. Run it with `bun run dead-code`.
 *
 * Entry points are the whole problem here. Next routes, Storybook stories and
 * the two workspace packages are consumed by tooling rather than by an import,
 * so each one has to be a declared root or knip reports live code as dead.
 * knip's next/storybook/jest/playwright/tsup plugins cover most of that; the
 * entries below are the cases those plugins cannot see.
 */
const config: KnipConfig = {
  workspaces: {
    ".": {
      entry: [
        // .storybook/main.ts aliases these through path.resolve(), which knip
        // cannot follow.
        ".storybook/mocks/*.tsx",
        // A compile-time assertion file: it has no importer on purpose, and
        // earns its place by turning a missing locale key into a type error.
        "src/i18n/messages/keyParity.ts",
        // Loaded by .oxlintrc.json `jsPlugins`.
        "tools/oxlint/anti-slop/index.ts",
        "tools/oxlint/i18n/index.ts",
        // Run by package.json scripts, not imported.
        "tools/type-check/index.ts",
        "tools/dead-code/index.ts",
        // Reached from src/app/globals.css through Tailwind's `@config`, which
        // knip does not follow. It requires the theme config, which in turn
        // requires the typography plugin.
        "tailwind.config.js",
        "tailwind-themes/tailwind.config.js",
      ],
      project: [
        "src/**/*.{ts,tsx}",
        "tools/**/*.{ts,tsx}",
        "tailwind.config.js",
        "tailwind-themes/tailwind.config.js",
      ],
      ignore: [
        // Gitignored; generated at build time.
        "src/lib/generated/**",
        // Deliberately broken sample code for the dead-code checker's tests.
        "tools/dead-code/__tests__/fixtures/**",
      ],
      ignoreDependencies: [
        // Next resolves these itself; no source file names them.
        "sharp",
        // Imported from CSS, which knip does not parse for dependencies.
        "tw-animate-css",
        // web/ consumes both workspace packages through the @opal/* tsconfig
        // alias and `transpilePackages`, never by package name, so knip sees
        // no import of either.
        "@onyx-ai/opal",
        "@onyx-ai/shared",
        // Used inside lib/opal/src, where they are peer dependencies. The root
        // app resolves opal from source, so the root install needs them too —
        // knip attributes the import to the opal workspace and calls the root
        // declaration unused.
        "@radix-ui/react-avatar",
        "@radix-ui/react-popover",
        "@radix-ui/react-tabs",
        "@tanstack/react-table",
        "clsx",
        "copy-to-clipboard",
        "react-day-picker",
        "tailwind-merge",
        // Ships with next; there is nothing to declare.
        "server-only",
        // knip's jest plugin misreads "@jest-environment comments" in the
        // jest.config.js docblock as a module specifier.
        "comments",
      ],
    },

    // Published to npm as @onyx-ai/opal. The tsup entry list is the public API
    // surface, so it is the root set — see lib/opal/tsup.config.ts.
    "lib/opal": {
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
        "scripts/bundle-css.mjs",
      ],
      project: ["src/**/*.{ts,tsx}"],
      // tsup provides the esbuild types that tsup.config.ts imports.
      ignoreDependencies: ["esbuild"],
    },

    // Private, but /workspace/mobile imports it from outside this workspace.
    // Its package.json `exports` are therefore all roots: knip must never
    // report a shared export dead just because web/ does not use it.
    "lib/shared": {
      entry: [
        "src/index.ts",
        "src/contracts/index.ts",
        "src/types/index.ts",
        "src/utils/index.ts",
        "style-dictionary.config.mjs",
        "scripts/*.mjs",
      ],
      project: ["src/**/*.ts"],
    },
  },

  // A declaration file describes code that lives elsewhere; an unused ambient
  // type is not dead code.
  ignore: ["**/*.d.ts"],

  // Route files, stories and configs export for the framework, never for an
  // importer. Reporting their exports would be pure noise.
  includeEntryExports: false,

  rules: {
    files: "error",
    dependencies: "error",
    devDependencies: "error",
    optionalPeerDependencies: "error",
    unlisted: "error",
    binaries: "error",
    unresolved: "error",
    exports: "error",
    types: "error",
    duplicates: "error",
    // Per-member resolution is noisy on a React codebase, and the export-level
    // rules above already gate the public surface.
    enumMembers: "off",
  },
};

export default config;
