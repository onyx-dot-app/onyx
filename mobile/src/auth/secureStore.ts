// Persistent, OS-encrypted storage for the Onyx mobile JWT.
//
// After a successful login (email/password or Google OAuth — see authClient.ts)
// the backend mints a short-lived JWT bearer token. We persist it here and inject
// it as `Authorization: Bearer <jwt>` on every request (see getAuthHeaders.ts).
//
// expo-secure-store is backed by the iOS Keychain / Android Keystore, so the
// token survives app restarts but never lands in plain JS-accessible storage.
// The JWT is opaque to us: we store and send it verbatim, never parse or split it.
import * as SecureStore from "expo-secure-store";

/** SecureStore key under which the raw JWT is persisted. Opaque, app-internal. */
export const JWT_STORAGE_KEY = "onyx.jwt";

/**
 * Read the stored JWT, or `null` if the user is signed out / has never signed in.
 * SecureStore reads are async (Keychain/Keystore access); callers must await.
 */
export async function getToken(): Promise<string | null> {
  return SecureStore.getItemAsync(JWT_STORAGE_KEY);
}

/**
 * Persist the JWT verbatim. The token is opaque — no validation or parsing here;
 * the backend is the source of truth for its shape, claims, and expiry.
 */
export async function setToken(jwt: string): Promise<void> {
  await SecureStore.setItemAsync(JWT_STORAGE_KEY, jwt);
}

/**
 * Remove the stored JWT (sign-out / forced re-auth). Idempotent: deleting an
 * absent key is a no-op, so this is safe to call unconditionally.
 */
export async function deleteToken(): Promise<void> {
  await SecureStore.deleteItemAsync(JWT_STORAGE_KEY);
}
