// Metro config for the standalone Onyx mobile Expo app.
// Wrapped with NativeWind so Tailwind classes compile through the bundler.

const { getDefaultConfig } = require("expo/metro-config");
const { withNativeWind } = require("nativewind/metro");

const config = getDefaultConfig(__dirname);

module.exports = withNativeWind(config, { input: "./global.css" });
