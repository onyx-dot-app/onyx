module.exports = {
  preset: "ts-jest",
  testEnvironment: "jsdom",
  setupFilesAfterEnv: ["<rootDir>/tests/setup/jest.setup.ts"],

  // Performance: Use 50% of CPU cores for parallel execution
  // CI can override with --maxWorkers=1 or --runInBand if needed
  maxWorkers: "50%",

  moduleNameMapper: {
    // Path aliases
    "^@/(.*)$": "<rootDir>/src/$1",
    "^@tests/(.*)$": "<rootDir>/tests/$1",
    // Mock CSS imports
    "\\.(css|less|scss|sass)$": "identity-obj-proxy",
    // Mock static file imports
    "\\.(jpg|jpeg|png|gif|svg|woff|woff2|ttf|eot)$":
      "<rootDir>/tests/setup/fileMock.js",
  },

  testPathIgnorePatterns: ["/node_modules/", "/tests/e2e/", "/.next/"],

  transformIgnorePatterns: [
    "/node_modules/(?!(jose|@radix-ui|@headlessui|msw|until-async)/)",
  ],

  transform: {
    "^.+\\.tsx?$": [
      "ts-jest",
      {
        // Performance: Disable type-checking in tests (types are checked by tsc)
        isolatedModules: true,
        tsconfig: {
          jsx: "react-jsx",
        },
      },
    ],
  },

  // Performance: Cache results between runs
  cache: true,
  cacheDirectory: "<rootDir>/.jest-cache",

  collectCoverageFrom: [
    "src/**/*.{ts,tsx}",
    "!src/**/*.d.ts",
    "!src/**/*.stories.tsx",
  ],

  coveragePathIgnorePatterns: ["/node_modules/", "/tests/", "/.next/"],

  testMatch: ["**/*.{test,spec}.{ts,tsx}"],

  // Performance: Clear mocks automatically between tests
  clearMocks: true,
  resetMocks: false,
  restoreMocks: false,
};
