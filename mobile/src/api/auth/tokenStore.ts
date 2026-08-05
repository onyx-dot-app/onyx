// Tokens live in the keychain (expo-secure-store), never MMKV; scoped by instance
// URL so a bearer can't cross instances. Keychain survives uninstall, so logout deletes explicitly.
import * as SecureStore from "expo-secure-store";

import { getBaseUrl } from "@/api/config";

const ACCESS_TOKEN_KEY_PREFIX = "onyx.auth.access_token";
const SAFE_KEY_CHAR = /^[A-Za-z0-9.-]$/;

// THIS_DEVICE_ONLY keeps the token out of iCloud/backups.
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
