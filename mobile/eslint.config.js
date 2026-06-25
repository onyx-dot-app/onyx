// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require("eslint/config");
const expoConfig = require("eslint-config-expo/flat");
const eslintConfigPrettier = require("eslint-config-prettier");

module.exports = defineConfig([
  expoConfig,
  // Must stay last to override conflicting rules.
  eslintConfigPrettier,
  {
    ignores: ["dist/*", ".expo/*", "node_modules/*", "android/*", "ios/*"],
  },
]);
