// Global test setup, registered via `setupFilesAfterEnv` in jest.config.js so it
// runs once the test framework is installed (i.e. `beforeEach` is available).
//
// Centralizes the cross-cutting reset every test needs: wipe the in-memory
// expo-secure-store keychain (see __mocks__/expo-secure-store.ts) and clear mock
// call history. Individual test files no longer repeat this boilerplate.
import { beforeEach, jest } from "@jest/globals";

// `requireMock` returns the manual mock from __mocks__/expo-secure-store.ts —
// the same instance the code under test uses — bypassing the real module's types
// so the test-only reset helper is reachable.
const secureStoreMock = jest.requireMock("expo-secure-store") as {
  __resetSecureStore: () => void;
};

beforeEach(() => {
  secureStoreMock.__resetSecureStore();
  jest.clearAllMocks();
});
