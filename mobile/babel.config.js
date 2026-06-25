// `jsxImportSource: "nativewind"` + the nativewind/babel preset enable `className` on RN components.
module.exports = function (api) {
  api.cache(true);
  return {
    presets: [
      ["babel-preset-expo", { jsxImportSource: "nativewind" }],
      "nativewind/babel",
    ],
  };
};
