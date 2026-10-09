import {
  DEFAULT_ONYX_DOMAIN,
  CHROME_SPECIFIC_STORAGE_KEYS,
} from "./constants.js";

export function normalizeOnyxDomain(domain) {
  if (typeof domain !== "string") return DEFAULT_ONYX_DOMAIN;
  const trimmed = domain.trim().replace(/\/+$/, "");
  return trimmed || DEFAULT_ONYX_DOMAIN;
}

// Managed storage is populated by enterprise policy (see managed_schema.json).
// It is read-only and takes precedence over anything the user sets locally.
async function getManaged(keys) {
  if (!chrome.storage.managed) return {};
  try {
    return await chrome.storage.managed.get(keys);
  } catch (error) {
    console.error(
      "Failed to read managed storage; using local settings",
      error
    );
    return {};
  }
}

export async function getManagedSettings() {
  return getManaged([
    CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN,
    CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB,
  ]);
}

export async function isNewTabOverrideManaged() {
  const managed = await getManaged(
    CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB
  );
  return (
    typeof managed[CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB] ===
    "boolean"
  );
}

export async function getOnyxDomain() {
  const managed = await getManaged(CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN);
  if (typeof managed[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN] === "string") {
    return normalizeOnyxDomain(
      managed[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]
    );
  }
  const result = await chrome.storage.local.get({
    [CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]: DEFAULT_ONYX_DOMAIN,
  });
  return normalizeOnyxDomain(result[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]);
}

export function setOnyxDomain(domain, callback) {
  chrome.storage.local.set(
    { [CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]: normalizeOnyxDomain(domain) },
    callback
  );
}

// Returns undefined when the user has never chosen, so callers can fall back
// to their own default.
export async function getUseOnyxAsDefaultNewTab() {
  const managed = await getManaged(
    CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB
  );
  const managedValue =
    managed[CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB];
  if (typeof managedValue === "boolean") return managedValue;
  const result = await chrome.storage.local.get(
    CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB
  );
  return result[CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB];
}

export async function setUseOnyxAsDefaultNewTab(value) {
  if (await isNewTabOverrideManaged()) return false;
  await chrome.storage.local.set({
    [CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB]: !!value,
  });
  return true;
}

export function isNewTabOverrideChange(changes, namespace) {
  return (
    (namespace === "local" || namespace === "managed") &&
    CHROME_SPECIFIC_STORAGE_KEYS.USE_ONYX_AS_DEFAULT_NEW_TAB in changes
  );
}
