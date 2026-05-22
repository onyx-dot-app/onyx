/**
 * Bun test preload — wired via `preload` in bunfig.toml.
 *
 * Replaces tests/setup/jest.setup.ts. Runs once per worker before any test
 * module is evaluated, so happy-dom's globals are in place by the time React
 * Testing Library or any component code imports `window`/`document`.
 */
import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { afterEach, expect, mock } from "bun:test";
import * as matchers from "@testing-library/jest-dom/matchers";

GlobalRegistrator.register({ url: "http://localhost/" });

expect.extend(matchers as any);

// Replicates jest.config.js moduleNameMapper entries that globally redirect
// problematic modules to lightweight test doubles. Bun has no equivalent of
// moduleNameMapper, so we wire each redirect via mock.module() in the preload.
// In `--isolate` mode the preload still runs per worker; the registered mock
// applies to every test file evaluated in that worker.
mock.module("@/providers/UserProvider", () => {
  // Lazy require keeps this synchronous so the mock is registered before any
  // test-file import of @/providers/UserProvider can resolve to the real module.
  return require("@tests/setup/mocks/components/UserProvider");
});

// React Testing Library auto-registers afterEach(cleanup) at module-load time,
// but in Bun that registration is scoped to whichever test file first imports
// RTL. Other files see a "stale" DOM and fail with multi-match errors.
// Registering cleanup here in the preload makes it fire for every test file.
const { cleanup } = await import("@testing-library/react");
afterEach(() => {
  cleanup();
});

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: mock().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: mock(),
    removeListener: mock(),
    addEventListener: mock(),
    removeEventListener: mock(),
    dispatchEvent: mock(),
  })),
});

(global as any).IntersectionObserver = class IntersectionObserver {
  constructor() {}
  disconnect() {}
  observe() {}
  takeRecords() {
    return [];
  }
  unobserve() {}
};

(global as any).ResizeObserver = class ResizeObserver {
  constructor() {}
  disconnect() {}
  observe() {}
  unobserve() {}
};

(global as any).scrollTo = mock();

// Radix UI's compose-refs triggers state updates during unmount that React
// reports as "not configured to support act" even with IS_REACT_ACT_ENVIRONMENT
// set, because the updates happen in the commit phase outside any act() boundary.
// Suppress only that specific message.
const SUPPRESSED_ERRORS = [
  "The current testing environment is not configured to support act",
] as const;

const originalError = console.error;
console.error = (...args: unknown[]) => {
  if (
    typeof args[0] === "string" &&
    SUPPRESSED_ERRORS.some((error) => (args[0] as string).includes(error))
  ) {
    return;
  }
  originalError.call(console, ...args);
};
