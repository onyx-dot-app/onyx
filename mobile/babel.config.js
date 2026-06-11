// NativeWind enables `className` on RN components: `jsxImportSource: "nativewind"`
// rewrites JSX, and the "nativewind/babel" preset wires the CSS-interop transform.
// babel-preset-expo also auto-adds the Reanimated/Worklets plugin when present.
module.exports = function (api) {
  api.cache(true);
  return {
    presets: [
      ["babel-preset-expo", { jsxImportSource: "nativewind" }],
      "nativewind/babel",
    ],
  };
};
