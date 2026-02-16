import {
  DEFAULT_ONYX_DOMAIN,
  CHROME_SPECIFIC_STORAGE_KEYS,
} from "./constants.js";

export async function getOnyxDomain() {
  const result = await chrome.storage.local.get({
    [CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]: DEFAULT_ONYX_DOMAIN,
  });
  return result[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN];
}

export function setOnyxDomain(domain, callback) {
  chrome.storage.local.set(
    { [CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]: domain },
    callback,
  );
}

export function getOnyxDomainSync() {
  return new Promise((resolve) => {
    getOnyxDomain(resolve);
  });
}
