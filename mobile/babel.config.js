// worklets:false disables babel-preset-expo's auto-add of react-native-worklets/plugin (registered with no
// options); we add it explicitly below with Bundle Mode (needed by react-native-streamdown). Exactly one
// worklets plugin must exist; it also covers reanimated 4.
module.exports = function (api) {
  api.cache(true);
  return {
    presets: [
      ["babel-preset-expo", { jsxImportSource: "nativewind", worklets: false }],
      "nativewind/babel",
    ],
    plugins: [
      // must stay last; importForwarding.moduleNames compiles remend's import into the worklet
      // bundle itself — without it, remend stays an external reference and calling it from inside
      // the worklet throws "Tried to synchronously call a Remote Function" at runtime.
      [
        "react-native-worklets/plugin",
        { bundleMode: true, importForwarding: { moduleNames: ["remend"] } },
      ],
    ],
  };
};
