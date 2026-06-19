// Default Expo Metro config wrapped with NativeWind so Tailwind classes compile
// through the bundler. `input` points at the Tailwind entry stylesheet.
const path = require("path");
const { getDefaultConfig } = require("expo/metro-config");
const { withNativeWind } = require("nativewind/metro");

const config = getDefaultConfig(__dirname);

// @onyx-ai/shared is a file: dependency that physically lives under web/lib/shared
// (outside this project root). Metro only resolves files inside watched folders, so
// add the package root explicitly. The package ships a self-contained dist/ with
// zero runtime deps, so we block its dev-only node_modules from Metro's crawl to
// avoid Haste collisions / duplicate-module resolution.
const sharedRoot = path.resolve(__dirname, "../web/lib/shared");
config.watchFolders = [...(config.watchFolders ?? []), sharedRoot];

// Resolve shared's subpath exports ("./nativewind-theme", "./native").
config.resolver.unstable_enablePackageExports = true;
// Keep module resolution anchored to mobile/node_modules (single React/RN copy).
config.resolver.nodeModulesPaths = [path.resolve(__dirname, "node_modules")];

const blockShared = /[/\\]web[/\\]lib[/\\]shared[/\\]node_modules[/\\].*/;
config.resolver.blockList = config.resolver.blockList
  ? [].concat(config.resolver.blockList, blockShared)
  : blockShared;

module.exports = withNativeWind(config, { input: "./src/global.css" });
