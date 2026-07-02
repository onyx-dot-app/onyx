// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require("eslint/config");
const expoConfig = require("eslint-config-expo/flat");
const eslintConfigPrettier = require("eslint-config-prettier");

module.exports = defineConfig([
  expoConfig,
  // Must stay last to override conflicting rules.
  eslintConfigPrettier,
  {
    // eslint-config-expo's TS override sets a node-only import resolver, which
    // ignores package.json `exports`, so @onyx-ai/shared subpaths (e.g.
    // "/native") fail import/no-unresolved. Re-enable the exports-aware resolver.
    settings: {
      "import/resolver": { typescript: true, node: true },
    },
  },
  {
    ignores: ["dist/*", ".expo/*", "node_modules/*", "android/*", "ios/*"],
  },
]);
