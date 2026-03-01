import { DEFAULT_ONYX_DOMAIN, STORAGE_KEYS } from "./constants.js";

export async function getOnyxDomain() {
  const result = await browser.storage.local.get({
    [STORAGE_KEYS.ONYX_DOMAIN]: DEFAULT_ONYX_DOMAIN,
  });
  return result[STORAGE_KEYS.ONYX_DOMAIN];
}

export function setOnyxDomain(domain) {
  return browser.storage.local.set({
    [STORAGE_KEYS.ONYX_DOMAIN]: domain,
  });
}

export function getOnyxDomainSync() {
  return getOnyxDomain();
}
