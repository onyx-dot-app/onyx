// Metro config for the standalone Onyx mobile Expo app.
// Wrapped with NativeWind so Tailwind classes compile through the bundler.

const { getDefaultConfig } = require("expo/metro-config");
const { withNativeWind } = require("nativewind/metro");

const config = getDefaultConfig(__dirname);

// markdown-it (used by @ronradtke/react-native-markdown-display) does a bare
// `require("punycode")`, which under Metro/Hermes resolves to the absent Node
// core module. Alias it to the real npm `punycode` package — note the trailing
// slash: `require.resolve("punycode/")` points at node_modules/punycode, while
// `require.resolve("punycode")` would return the deprecated Node builtin string.
config.resolver.extraNodeModules = {
  ...config.resolver.extraNodeModules,
  punycode: require.resolve("punycode/"),
};

module.exports = withNativeWind(config, { input: "./global.css" });
