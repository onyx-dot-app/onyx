// Auth-token storage.
//
// `apiFetch` reads the access token via `getToken()`. The future login flow
// calls `setToken(token)`; logout calls `setToken(null)`.
//
// Tokens are credentials, so they live in the device keychain via
// expo-secure-store — NOT in MMKV (which is reserved for non-secret cache /
// persisted UI state). Tests mock the `expo-secure-store` module.
//
// SECURITY TODO — must be handled when the login/logout flow lands (these are
// dormant today only because no token exists, so /api/me always 403s and no
// user data is ever cached):
//   1. Logout must `queryClient.clear()` AND purge the persisted snapshot
//      (`persister.removeClient()` / `queryStorage.clearAll()`) — otherwise the
//      previous user's cached /api/me PII survives logout for up to 24h.
//   2. Scope the cached-user query key to the authenticated identity (or bump a
//      session epoch on login/logout) so user B can never read user A's cache.
//   3. The query-cache MMKV instance (state/storage.ts) is unencrypted; once
//      /api/me succeeds, email/role are written to disk in plaintext. Give that
//      instance an `encryptionKey` (sourced from expo-secure-store), or exclude
//      PII queries from persistence via `dehydrateOptions.shouldDehydrateQuery`.
import * as SecureStore from "expo-secure-store";

// SecureStore keys allow alphanumerics plus ".", "-", "_".
const ACCESS_TOKEN_KEY = "onyx.auth.access_token";

export function getToken(): Promise<string | null> {
  return SecureStore.getItemAsync(ACCESS_TOKEN_KEY);
}

export function setToken(token: string | null): Promise<void> {
  return token === null
    ? SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY)
    : SecureStore.setItemAsync(ACCESS_TOKEN_KEY, token);
}
