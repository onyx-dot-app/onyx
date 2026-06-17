// Manual Jest mock for expo-secure-store.
//
// expo-secure-store is a node module, so Jest applies this mock AUTOMATICALLY to
// every test (the file sits adjacent to node_modules) — no `jest.mock(...)` call
// is needed in individual test files. It mirrors the keychain's get/set/delete
// semantics with an in-memory Map. (MMKV needs no equivalent: react-native-mmkv
// v4 self-mocks under Jest via its own `isTest()` check.)
//
// `__resetSecureStore()` clears the backing store between tests; it is wired into
// a global `beforeEach` in jest.setup.ts, so tests start with an empty keychain.
import { jest } from "@jest/globals";

const store = new Map<string, string>();

// Keychain-accessibility constant. The real value is an enum number, but the mock
// ignores the options arg entirely, so a readable sentinel is all that's needed.
export const WHEN_UNLOCKED_THIS_DEVICE_ONLY = "WHEN_UNLOCKED_THIS_DEVICE_ONLY";

export const getItemAsync = jest.fn(
  (key: string): Promise<string | null> =>
    Promise.resolve(store.get(key) ?? null),
);

export const setItemAsync = jest.fn(
  (key: string, value: string, _options?: unknown): Promise<void> => {
    store.set(key, value);
    return Promise.resolve();
  },
);

export const deleteItemAsync = jest.fn(
  (key: string, _options?: unknown): Promise<void> => {
    store.delete(key);
    return Promise.resolve();
  },
);

// Test-only helper (not part of the real module): wipe the in-memory keychain.
export function __resetSecureStore(): void {
  store.clear();
}
