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
    // Mock CSS files (before path alias resolution)
    // CSS/static assets cannot be executed in tests and must be mocked
    "^@/.*\\.(css|less|scss|sass)$": "<rootDir>/tests/setup/mocks/cssMock.js",
    "^katex/dist/katex.min.css$": "<rootDir>/tests/setup/mocks/cssMock.js",
    "\\.(css|less|scss|sass)$": "<rootDir>/tests/setup/mocks/cssMock.js",
    // Mock static file imports
    "\\.(jpg|jpeg|png|gif|svg|woff|woff2|ttf|eot)$":
      "<rootDir>/tests/setup/fileMock.js",
    // Mock specific components that have complex dependencies
    "^@/components/user/UserProvider$":
      "<rootDir>/tests/setup/mocks/components/UserProvider.tsx",
    // Path aliases (must come after specific mocks)
    "^@/(.*)$": "<rootDir>/src/$1",
    "^@tests/(.*)$": "<rootDir>/tests/$1",
    "^@opal$": "<rootDir>/lib/opal/src/index.ts",
    "^@opal/(.*)$": "<rootDir>/lib/opal/src/$1",
  },

  testPathIgnorePatterns: ["/node_modules/", "/tests/e2e/", "/.next/"],

  // Transform ES Modules in node_modules to CommonJS for Jest compatibility
  // Add packages here when you encounter: "SyntaxError: Unexpected token 'export'"
  // These packages ship as ESM and need to be transformed to work in Jest
  transformIgnorePatterns: [
    "/node_modules/(?!(" +
      [
        // Auth & Security
        "jose",
        // UI Libraries
        "@radix-ui",
        "@headlessui",
        "@phosphor-icons",
        // Testing & Mocking
        "msw",
        "until-async",
        // Markdown & Syntax Highlighting
        "react-markdown",
        "remark-.*", // All remark packages
        "rehype-.*", // All rehype packages
        "unified",
        "lowlight",
        "highlight\\.js",
        // Markdown Utilities
        "bail",
        "is-plain-obj",
        "trough",
        "vfile",
        "vfile-.*", // All vfile packages
        "unist-.*", // All unist packages
        "mdast-.*", // All mdast packages
        "hast-.*", // All hast packages
        "hastscript",
        "micromark.*", // All micromark packages
        "decode-named-character-reference",
        "character-entities",
        "devlop",
        "comma-separated-tokens",
        "property-information",
        "space-separated-tokens",
        "html-void-elements",
        "html-url-attributes",
        "aria-attributes",
        "web-namespaces",
        "svg-tag-names",
        "style-to-object",
        "inline-style-parser",
        "ccount",
        "escape-string-regexp",
        "markdown-table",
        "longest-streak",
        "zwitch",
        "trim-lines",
        "stringify-entities",
        "estree-.*", // All estree packages
      ].join("|") +
      ")/)",
  ],

  transform: {
    "^.+\\.(t|j)sx?$": [
      "ts-jest",
      {
        // Performance: Disable type-checking in tests (types are checked by tsc)
        isolatedModules: true,
        tsconfig: {
          jsx: "react-jsx",
          // Allow ts-jest to process JavaScript files from node_modules
          allowJs: true,
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
        "**/src/app/**/services/*.test.ts",
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
        "**/src/refresh-components/**/*.test.tsx",
        // Add more patterns here as you add more integration tests
      ],
    },
  ],
};
