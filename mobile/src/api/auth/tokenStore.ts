// Tokens are credentials, so they live in the device keychain via
// expo-secure-store, NOT in MMKV (non-secret cache only). Scoped by instance
// URL so user B can't reuse another instance's bearer token. iOS Keychain
// survives uninstall with no bulk-clear, so logout deletes the entry explicitly.
import * as SecureStore from "expo-secure-store";

import { getBaseUrl } from "@/api/config";

// SecureStore keys allow alphanumerics plus ".", "-", "_".
const ACCESS_TOKEN_KEY_PREFIX = "onyx.auth.access_token";
const SAFE_KEY_CHAR = /^[A-Za-z0-9.-]$/;

// THIS_DEVICE_ONLY keeps the token out of iCloud/backups; WHEN_UNLOCKED gates
// reads on an unlocked device.
const TOKEN_KEYCHAIN_OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

function encodeSecureStoreKeyPart(value: string): string {
  // SecureStore rejects ":" and "/", so encode unsupported chars deterministically.
  return Array.from(value)
    .map((char) =>
      SAFE_KEY_CHAR.test(char)
        ? char
        : `_${(char.codePointAt(0) ?? 0).toString(16)}_`,
    )
    .join("");
}

function getAccessTokenKey(): string {
  return `${ACCESS_TOKEN_KEY_PREFIX}.${encodeSecureStoreKeyPart(getBaseUrl())}`;
}

export function getToken(): Promise<string | null> {
  return SecureStore.getItemAsync(getAccessTokenKey());
}

export function setToken(token: string | null): Promise<void> {
  return token === null
    ? SecureStore.deleteItemAsync(getAccessTokenKey())
    : SecureStore.setItemAsync(
        getAccessTokenKey(),
        token,
        TOKEN_KEYCHAIN_OPTIONS,
      );
}
