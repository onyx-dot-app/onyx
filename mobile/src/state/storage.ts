// react-native-mmkv v4 has no `new MMKV()` — use createMMKV. Two separate instances so a
// query-cache clear can't touch other persisted state.
import { createMMKV, type MMKV } from "react-native-mmkv";

export const appStorage: MMKV = createMMKV({ id: "onyx.app" });
export const queryStorage: MMKV = createMMKV({ id: "onyx.query-cache" });

export function makeMmkvStorage(mmkv: MMKV) {
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
