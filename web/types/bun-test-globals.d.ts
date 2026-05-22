/// <reference types="bun-types/test-globals" />

import type { TestingLibraryMatchers } from "@testing-library/jest-dom/matchers";

declare module "bun:test" {
  interface Matchers<T = unknown> extends TestingLibraryMatchers<
    typeof expect.stringContaining,
    T
  > {}
  interface AsymmetricMatchers extends TestingLibraryMatchers<
    typeof expect.stringContaining,
    unknown
  > {}
}
