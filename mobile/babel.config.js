// Babel config for the standalone Onyx mobile Expo app.
// `jsxImportSource: "nativewind"` enables className on RN components; the
// "nativewind/babel" preset wires up the CSS-interop transform.
module.exports = function (api) {
  api.cache(true);
  return {
    presets: [
      ["babel-preset-expo", { jsxImportSource: "nativewind" }],
      "nativewind/babel",
    ],
  };
};
