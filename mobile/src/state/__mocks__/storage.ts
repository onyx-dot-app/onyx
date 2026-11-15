/*
 * In-memory stand-in for the MMKV instances — the real module reaches for a native Nitro module
 * jest has no binary for.
 */
interface FakeMMKV {
  getString: (key: string) => string | undefined;
  getBoolean: (key: string) => boolean | undefined;
  set: (key: string, value: string | boolean | number) => void;
  remove: (key: string) => void;
  clearAll: () => void;
}

function createFake(): FakeMMKV {
  const values = new Map<string, string | boolean | number>();
  return {
    getString: (key) => {
      const value = values.get(key);
      return typeof value === "string" ? value : undefined;
    },
    getBoolean: (key) => {
      const value = values.get(key);
      return typeof value === "boolean" ? value : undefined;
    },
    set: (key, value) => {
      values.set(key, value);
    },
    remove: (key) => {
      values.delete(key);
    },
    clearAll: () => values.clear(),
  };
}

export const appStorage = createFake();
export const queryStorage = createFake();

export function makeMmkvStorage(mmkv: FakeMMKV) {
  return {
    getItem: (name: string): string | null => mmkv.getString(name) ?? null,
    setItem: (name: string, value: string): void => {
      mmkv.set(name, value);
    },
    removeItem: (name: string): void => {
      mmkv.remove(name);
    },
  };
}
