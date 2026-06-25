const path = require("path");
const { getDefaultConfig } = require("expo/metro-config");
const { withNativeWind } = require("nativewind/metro");

const config = getDefaultConfig(__dirname);

// @onyx-ai/shared lives outside this root (web/lib/shared), so add it to watchFolders;
// block its dev-only node_modules from the crawl to avoid Haste/duplicate-module collisions.
const sharedRoot = path.resolve(__dirname, "../web/lib/shared");
config.watchFolders = [...(config.watchFolders ?? []), sharedRoot];

// Resolve shared's subpath exports ("./nativewind-theme", "./native").
config.resolver.unstable_enablePackageExports = true;
// Anchor resolution to mobile/node_modules (single React/RN copy).
config.resolver.nodeModulesPaths = [path.resolve(__dirname, "node_modules")];

const blockShared = /[/\\]web[/\\]lib[/\\]shared[/\\]node_modules[/\\].*/;
config.resolver.blockList = config.resolver.blockList
  ? [].concat(config.resolver.blockList, blockShared)
  : blockShared;

module.exports = withNativeWind(config, { input: "./src/global.css" });
