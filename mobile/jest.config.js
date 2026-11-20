const expoPreset = require("jest-expo/jest-preset");

module.exports = {
  preset: "jest-expo",
  moduleNameMapper: {
    "^@babel/runtime/(.*)$": "<rootDir>/node_modules/@babel/runtime/$1",
    "^@onyx-ai/shared/acp$":
      "<rootDir>/node_modules/@onyx-ai/shared/src/contracts/acp.ts",
    "^@/(.*)$": "<rootDir>/src/$1",
  },
  testMatch: ["<rootDir>/src/**/__tests__/**/*.test.ts?(x)"],
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  // Extend jest-expo's curated pattern to transpile nativewind/@rn-primitives (untranspiled JSX/ESM).
  transformIgnorePatterns: [
    expoPreset.transformIgnorePatterns[0].replace(
      "standard-navigation",
      "standard-navigation|nativewind|react-native-css-interop|@rn-primitives|@onyx-ai",
    ),
    ...expoPreset.transformIgnorePatterns.slice(1),
  ],
};
