const path = require("path");
const { getDefaultConfig } = require("expo/metro-config");
const { withNativeWind } = require("nativewind/metro");
const {
  getBundleModeMetroConfig,
} = require("react-native-worklets/bundleMode");

let config = getDefaultConfig(__dirname);

// @onyx-ai/shared lives outside this root (web/lib/shared), so add it to watchFolders;
// block its dev-only node_modules from the crawl to avoid Haste/duplicate-module collisions.
const sharedRoot = path.resolve(__dirname, "../web/lib/shared");

// Bundle Mode emits worklet modules under react-native-worklets/.worklets after the initial
// crawl, so Metro can't hash them and throws "Failed to get the SHA-1". Watching the folder isn't
// enough on its own — the actual fix is Software Mansion's official metro patch
// (patches/metro@0.84.4.patch; see patches/README.md and metro#330).
const workletsDir = path.resolve(
  __dirname,
  "node_modules/react-native-worklets/.worklets",
);

config.watchFolders = [...(config.watchFolders ?? []), sharedRoot, workletsDir];

// Resolve shared's subpath exports ("./nativewind-theme", "./native").
config.resolver.unstable_enablePackageExports = true;
// Anchor resolution to mobile/node_modules (single React/RN copy).
config.resolver.nodeModulesPaths = [path.resolve(__dirname, "node_modules")];

const blockShared = /[/\\]web[/\\]lib[/\\]shared[/\\]node_modules[/\\].*/;
config.resolver.blockList = config.resolver.blockList
  ? [].concat(config.resolver.blockList, blockShared)
  : blockShared;

// Bundle Mode (getBundleModeMetroConfig) mutates `config` in place and sets
// config.resolver.resolveRequest. It MUST run before withNativeWind so that nativewind's
// css-interop resolver captures the bundle-mode router as its inner resolver and chains to it.
// Route only .worklets/* through the Bundle Mode resolver; keep default resolution otherwise.
const defaultResolveRequest = config.resolver.resolveRequest;
config = getBundleModeMetroConfig(config);
const bundleModeResolveRequest = config.resolver.resolveRequest;
config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (moduleName.startsWith("react-native-worklets/.worklets/")) {
    return bundleModeResolveRequest(context, moduleName, platform);
  }
  if (defaultResolveRequest) {
    return defaultResolveRequest(context, moduleName, platform);
  }
  return context.resolveRequest(context, moduleName, platform);
};

// withNativeWind LAST: it returns a new config that preserves watchFolders verbatim and wraps
// (chains to) the bundle-mode resolveRequest above — so the .worklets routing survives.
module.exports = withNativeWind(config, { input: "./src/global.css" });
