import "@testing-library/jest-dom";
import { TextEncoder, TextDecoder } from "util";

// Tell React 18+ this is a test environment where act() is available
// This suppresses "not configured to support act(...)" warnings
// @ts-ignore
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Polyfill TextEncoder/TextDecoder (required for some libraries)
global.TextEncoder = TextEncoder as any;
global.TextDecoder = TextDecoder as any;

// Only set up browser-specific mocks if we're in a jsdom environment
if (typeof window !== "undefined") {
  // Polyfill fetch for jsdom
  // @ts-ignore
  import("whatwg-fetch");

  // Mock BroadcastChannel for JSDOM
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
}

// Suppress specific known console errors that are not actionable in tests.
// This pattern is recommended for handling third-party library warnings:
// https://github.com/testing-library/user-event/issues/1114#issuecomment-1876164351
//
// Radix UI's compose-refs package triggers state updates during component unmount
// which causes React to emit "not configured to support act" warnings. This happens
// because the updates occur in React's commit phase, outside of any act() boundary.
// The IS_REACT_ACT_ENVIRONMENT flag doesn't help because jsdom's globalThis is set
// up before our setup file runs.
const SUPPRESSED_ERRORS = [
  "The current testing environment is not configured to support act",
] as const;

const originalError = console.error;
console.error = (...args: any[]) => {
  if (
    typeof args[0] === "string" &&
    SUPPRESSED_ERRORS.some((error) => args[0].includes(error))
  ) {
    return;
  }
  originalError.call(console, ...args);
};
