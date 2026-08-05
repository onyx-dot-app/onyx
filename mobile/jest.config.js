const expoPreset = require("jest-expo/jest-preset");

module.exports = {
  preset: "jest-expo",
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1",
  },
  testMatch: ["<rootDir>/src/**/__tests__/**/*.test.ts?(x)"],
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  // Extend jest-expo's curated pattern to transpile nativewind/@rn-primitives (untranspiled JSX/ESM).
  transformIgnorePatterns: [
    expoPreset.transformIgnorePatterns[0].replace(
      "standard-navigation",
      "standard-navigation|nativewind|react-native-css-interop|@rn-primitives",
    ),
    ...expoPreset.transformIgnorePatterns.slice(1),
  ],
};
