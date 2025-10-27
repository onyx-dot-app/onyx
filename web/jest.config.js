/**
 * Jest configuration with separate projects for different test environments.
 *
 * We use two separate projects:
 * 1. "unit" - Node environment for pure unit tests (no DOM needed)
 * 2. "integration" - jsdom environment for React integration tests
 *
 * This allows us to run tests with the correct environment automatically
 * without needing @jest-environment comments in every test file.
 */

// Shared configuration
const sharedConfig = {
  preset: "ts-jest",
  setupFilesAfterEnv: ["<rootDir>/tests/setup/jest.setup.ts"],

  // Performance: Use 50% of CPU cores for parallel execution
  maxWorkers: "50%",

  moduleNameMapper: {
    // Mock react-markdown and related packages
    "^react-markdown$": "<rootDir>/tests/setup/__mocks__/react-markdown.tsx",
    "^remark-gfm$": "<rootDir>/tests/setup/__mocks__/remark-gfm.ts",
    // Mock UserProvider
    "^@/components/user/UserProvider$":
      "<rootDir>/tests/setup/__mocks__/@/components/user/UserProvider.tsx",
    // Path aliases (must come after specific mocks)
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
    "/node_modules/(?!(jose|@radix-ui|@headlessui|@phosphor-icons|msw|until-async|react-markdown|remark-gfm|remark-parse|unified|bail|is-plain-obj|trough|vfile|unist-.*|mdast-.*|micromark.*|decode-named-character-reference|character-entities)/)",
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

  // Performance: Clear mocks automatically between tests
  clearMocks: true,
  resetMocks: false,
  restoreMocks: false,
};

module.exports = {
  projects: [
    {
      displayName: "unit",
      ...sharedConfig,
      testEnvironment: "node",
      testMatch: [
        // Pure unit tests that don't need DOM
        "**/src/**/codeUtils.test.ts",
        "**/src/lib/**/*.test.ts",
        // Add more patterns here as you add more unit tests
      ],
    },
    {
      displayName: "integration",
      ...sharedConfig,
      testEnvironment: "jsdom",
      testMatch: [
        // React component integration tests
        "**/src/app/**/*.test.tsx",
        "**/src/components/**/*.test.tsx",
        "**/src/lib/**/*.test.tsx",
        // Add more patterns here as you add more integration tests
      ],
    },
  ],
};
