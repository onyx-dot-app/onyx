// Jest config for the mobile app.
//
// `jest-expo` provides the Expo/React Native babel transform, module resolution,
// and native-module shims. We add the `@/` path alias (matching tsconfig) so
// tests can import + mock app modules by their canonical path.
//
// Native-module mocking is centralized, not per-test:
//   - MMKV: react-native-mmkv v4 self-mocks under Jest (its own `isTest()`), so
//     `@/state/storage` works against an in-memory store with no setup.
//   - expo-secure-store: a manual mock at __mocks__/expo-secure-store.ts is
//     auto-applied to every test (it's a node module).
//   - jest.setup.ts (setupFilesAfterEnv) resets that keychain + clears mock call
//     history before each test.
//
// Component tests render UI deps that ship untranspiled JSX/ESM (nativewind,
// @rn-primitives). jest-expo's default transformIgnorePatterns already allow-lists
// react-native* / expo*; we extend its curated first pattern with those two rather
// than hand-roll (and lose) the rest.
const expoPreset = require("jest-expo/jest-preset");

module.exports = {
  preset: "jest-expo",
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1",
  },
  testMatch: ["<rootDir>/src/**/__tests__/**/*.test.ts?(x)"],
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  transformIgnorePatterns: [
    expoPreset.transformIgnorePatterns[0].replace(
      "standard-navigation",
      "standard-navigation|nativewind|react-native-css-interop|@rn-primitives",
    ),
    ...expoPreset.transformIgnorePatterns.slice(1),
  ],
};
