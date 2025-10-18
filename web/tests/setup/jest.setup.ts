import "@testing-library/jest-dom";
import { TextEncoder, TextDecoder } from "util";
import "whatwg-fetch";

// Polyfill TextEncoder/TextDecoder for JSDOM (required by MSW)
global.TextEncoder = TextEncoder;
global.TextDecoder = TextDecoder as any;

// Mock BroadcastChannel for JSDOM (required by MSW)
global.BroadcastChannel = class BroadcastChannel {
  constructor(public name: string) {}
  postMessage() {}
  close() {}
  addEventListener() {}
  removeEventListener() {}
  dispatchEvent() {
    return true;
  }
} as any;

// NOTE: MSW server is NOT imported globally due to ESM compatibility issues with Jest.
// Import it directly in tests that need API mocking:
// import { server } from "@tests/setup/msw-server";

// Mock window.matchMedia for responsive components
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: jest.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: jest.fn(), // deprecated
    removeListener: jest.fn(), // deprecated
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  })),
});

// Mock IntersectionObserver
global.IntersectionObserver = class IntersectionObserver {
  constructor() {}
  disconnect() {}
  observe() {}
  takeRecords() {
    return [];
  }
  unobserve() {}
} as any;

// Mock ResizeObserver
global.ResizeObserver = class ResizeObserver {
  constructor() {}
  disconnect() {}
  observe() {}
  unobserve() {}
} as any;

// Mock window.scrollTo
global.scrollTo = jest.fn();

// Suppress console errors in tests (optional - comment out if you want to see them)
const originalError = console.error;
beforeAll(() => {
  console.error = (...args: any[]) => {
    // Filter out known React warnings that are not actionable in tests
    if (
      typeof args[0] === "string" &&
      (args[0].includes("Warning: ReactDOM.render") ||
        args[0].includes("Not implemented: HTMLFormElement.prototype.submit"))
    ) {
      return;
    }
    originalError.call(console, ...args);
  };
});

afterAll(() => {
  console.error = originalError;
});
