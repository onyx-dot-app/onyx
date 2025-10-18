import "@testing-library/jest-dom";
import { TextEncoder, TextDecoder } from "util";

// Polyfill TextEncoder/TextDecoder (required for some libraries)
global.TextEncoder = TextEncoder;
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

// Suppress console errors in tests (optional - comment out if you want to see them)
// const originalError = console.error;
// beforeAll(() => {
//   console.error = (...args: any[]) => {
//     // Filter out known React warnings that are not actionable in tests
//     if (
//       typeof args[0] === "string" &&
//       (args[0].includes("Warning: ReactDOM.render") ||
//         args[0].includes("Not implemented: HTMLFormElement.prototype.submit"))
//     ) {
//       return;
//     }
//     originalError.call(console, ...args);
//   };
// });

// afterAll(() => {
//   console.error = originalError;
// });
