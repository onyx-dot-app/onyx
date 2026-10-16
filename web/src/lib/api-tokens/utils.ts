import {
  API_TOKEN_PLATFORM_LABELS,
  EMPTY_API_TOKEN_VALUE,
} from "@/lib/api-tokens/constants";
import type { ApiTokenPlatform, ApiTokenValue } from "@/lib/api-tokens/types";

/** The brand name a platform shows as, e.g. "OpenAI" for "openai". */
export function getApiTokenPlatformLabel(platform: ApiTokenPlatform): string {
  return API_TOKEN_PLATFORM_LABELS.get(platform) ?? platform;
}

/** A field's starting value: the key a saved row already uses, or empty. */
export function initialApiTokenValue(
  tokenId: number | null | undefined
): ApiTokenValue {
  return tokenId == null
    ? EMPTY_API_TOKEN_VALUE
    : { type: "existing", id: tokenId };
}

/** True when the field holds no key. */
export function isApiTokenValueEmpty(value: ApiTokenValue): boolean {
  return value.type === "new" && value.value.trim() === "";
}

/**
 * What a request sends for the field. An empty field is left out of the
 * request, which keeps a saved row's current key; clearing the field never
 * removes a key.
 */
export function toApiTokenPayload(
  value: ApiTokenValue
): ApiTokenValue | undefined {
  return isApiTokenValueEmpty(value) ? undefined : value;
}
