// Persistent JWT storage backed by the iOS Keychain / Android Keystore, so the token
// survives restarts but never lands in plain JS-accessible storage. The JWT is opaque:
// we store and send it verbatim, never parse it.
import * as SecureStore from "expo-secure-store";

export const JWT_STORAGE_KEY = "onyx.jwt";

export async function getToken(): Promise<string | null> {
  return SecureStore.getItemAsync(JWT_STORAGE_KEY);
}

export async function setToken(jwt: string): Promise<void> {
  await SecureStore.setItemAsync(JWT_STORAGE_KEY, jwt);
}

// Idempotent: deleting an absent key is a no-op, so this is safe to call unconditionally.
export async function deleteToken(): Promise<void> {
  await SecureStore.deleteItemAsync(JWT_STORAGE_KEY);
}
