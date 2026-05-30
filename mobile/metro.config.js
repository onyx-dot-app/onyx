// Metro config for the standalone Onyx mobile Expo app.
// (NativeWind's withNativeWind() wrapper is added later — see doc 05.)

const { getDefaultConfig } = require("expo/metro-config");

const config = getDefaultConfig(__dirname);

module.exports = config;
