// Auto-applied to every test (node module manual mock); keychain semantics over an in-memory Map.
import { jest } from "@jest/globals";

const store = new Map<string, string>();

// Readable sentinel; the mock ignores the options arg.
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

// Test-only helper: wipe the in-memory keychain.
export function __resetSecureStore(): void {
  store.clear();
}
