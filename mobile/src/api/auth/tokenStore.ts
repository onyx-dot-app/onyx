// Auth-token storage.
//
// `apiFetch` reads the access token via `getToken()`. `SessionManager` calls
// `setToken(token)` on login and `setToken(null)` on logout.
//
// Tokens are credentials, so they live in the device keychain via
// expo-secure-store — NOT in MMKV (which is reserved for non-secret cache /
// persisted UI state). Tests mock the `expo-secure-store` module.
//
// SECURITY (the TODOs flagged before the auth flow landed are now handled):
//   1. Logout purge — `SessionManager.logout()` clears the in-memory query
//      cache AND removes the persisted MMKV snapshot, so the previous user's
//      cached /api/me PII does not survive logout.
//   2. Cross-user isolation — login and logout both purge the entire cache, and
//      tokens are scoped by normalized instance URL, so user B can never read
//      user A's cached data or reuse another instance's bearer token.
//   3. PII at rest — the /api/me query is excluded from the persisted snapshot
//      (`dehydrateOptions` in `query/client.ts`), so email/role are never
//      written to the unencrypted query-cache MMKV instance. (Full at-rest
//      encryption of the cache is a later hardening, paired with expo-crypto.)
//   4. Keychain accessibility — the token is stored THIS_DEVICE_ONLY (kept out
//      of iCloud/encrypted backups and device transfers) and WHEN_UNLOCKED
//      (readable only while the device is unlocked). The iOS Keychain survives
//      app uninstall and has no bulk-clear, so logout deletes the entry
//      explicitly.
import * as SecureStore from "expo-secure-store";

import { getBaseUrl } from "@/api/config";

// SecureStore keys allow alphanumerics plus ".", "-", "_".
const ACCESS_TOKEN_KEY_PREFIX = "onyx.auth.access_token";
const SAFE_KEY_CHAR = /^[A-Za-z0-9.-]$/;

// When the OS keychain will release the stored token (not a login signal):
//   WHEN_UNLOCKED    — readable only while the device is unlocked.
//   THIS_DEVICE_ONLY — never synced to iCloud or restored onto another device.
const TOKEN_KEYCHAIN_OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

function encodeSecureStoreKeyPart(value: string): string {
  // The server URL scopes the token, but SecureStore rejects ":" and "/".
  // Encode unsupported characters into a deterministic safe suffix.
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
