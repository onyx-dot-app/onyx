// The user-chosen Onyx server base URL (the "enter your domain" value). Persisted
// across launches and held in memory so the API layer can read it synchronously after
// bootstrap. Unlike the JWT this is not a secret; SecureStore is reused only to avoid
// adding a storage dependency.
import * as SecureStore from "expo-secure-store";

import { appConfig } from "@/lib/config";

const SERVER_URL_KEY = "onyx.serverUrl";

let current: string | null = null;

/** The chosen server URL, or null if the user hasn't picked one yet. */
export function getServerUrl(): string | null {
  return current;
}

/**
 * The base URL every API call should use: the chosen server if set, else the
 * build-time default (so dev builds still boot without a domain screen).
 */
export function getApiBaseUrl(): string {
  return current ?? appConfig.apiBaseUrl;
}

/** Load the persisted server URL into memory. Call once at startup before any request. */
export async function hydrateServerUrl(): Promise<string | null> {
  current = await SecureStore.getItemAsync(SERVER_URL_KEY);
  return current;
}

/** Persist and adopt a server URL (trailing slashes trimmed). */
export async function setServerUrl(url: string): Promise<void> {
  const normalized = url.trim().replace(/\/+$/, "");
  current = normalized;
  await SecureStore.setItemAsync(SERVER_URL_KEY, normalized);
}

/** Forget the chosen server URL (e.g. when switching servers). */
export async function clearServerUrl(): Promise<void> {
  current = null;
  await SecureStore.deleteItemAsync(SERVER_URL_KEY);
}
