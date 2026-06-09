// Default Expo Metro config wrapped with NativeWind so Tailwind classes compile
// through the bundler. `input` points at the Tailwind entry stylesheet.
const { getDefaultConfig } = require("expo/metro-config");
const { withNativeWind } = require("nativewind/metro");

const config = getDefaultConfig(__dirname);

module.exports = withNativeWind(config, { input: "./src/global.css" });
