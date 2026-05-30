// Metro config for the Onyx mobile app inside the onyx Bun monorepo.
//
// Expo's Metro auto-detects monorepos since SDK 52, but we make the workspace root and
// the hoisted node_modules explicit so that edits in packages/* trigger Fast Refresh.
// (NativeWind's withNativeWind() wrapper is added later.)

const { getDefaultConfig } = require("expo/metro-config");
const path = require("path");

const projectRoot = __dirname;
const workspaceRoot = path.resolve(projectRoot, ".."); // onyx repo root

const config = getDefaultConfig(projectRoot);

// 1. Watch the whole monorepo so changes in packages/* (and web/lib/opal) hot-reload.
config.watchFolders = [workspaceRoot];

// 2. Resolve modules from the app first, then the hoisted root node_modules.
config.resolver.nodeModulesPaths = [
  path.resolve(projectRoot, "node_modules"),
  path.resolve(workspaceRoot, "node_modules"),
];

// 3. With a single hoisted tree, disable hierarchical lookup for deterministic resolution.
config.resolver.disableHierarchicalLookup = true;

module.exports = config;
