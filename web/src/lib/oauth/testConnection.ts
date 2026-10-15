import { oauthConfigRequest, type OAuthConfigFields } from "@/lib/oauth/config";
import type { OAuthTestRequest } from "@/lib/oauth/api";

export const OAUTH_TEST_ACTIVE_KEY = "onyx:oauth-config-test:active";
const TEST_KEY_PREFIX = "onyx:oauth-config-test:attempt:";
export const OAUTH_TEST_MESSAGE_TYPE = "onyx:oauth-config-test-result";

export function oauthTestRequest(
  fields: OAuthConfigFields,
  configId?: number | null
): OAuthTestRequest {
  const config = oauthConfigRequest(fields, Boolean(configId));
  return {
    ...config,
    oauth_config_id: configId ?? undefined,
    client_id: config.client_id || undefined,
    client_secret: config.client_secret || undefined,
  };
}

export function oauthTestStorageKey(state: string): string {
  return `${TEST_KEY_PREFIX}${state}`;
}

export type OAuthTestResult =
  | { status: "success"; supports_pkce: boolean }
  | { status: "failed" | "denied" | "interrupted" };

export interface OAuthTestMessage {
  type: typeof OAUTH_TEST_MESSAGE_TYPE;
  state: string;
  result: OAuthTestResult;
}

export function isOAuthTestResult(value: unknown): value is OAuthTestResult {
  if (!value || typeof value !== "object" || !("status" in value)) return false;
  if (value.status === "success") {
    return "supports_pkce" in value && typeof value.supports_pkce === "boolean";
  }
  return ["failed", "denied", "interrupted"].some(
    (status) => status === value.status
  );
}

export function isOAuthTestMessage(value: unknown): value is OAuthTestMessage {
  return Boolean(
    value &&
    typeof value === "object" &&
    "type" in value &&
    value.type === OAUTH_TEST_MESSAGE_TYPE &&
    "state" in value &&
    typeof value.state === "string" &&
    "result" in value &&
    isOAuthTestResult(value.result)
  );
}

export function oauthTestChannelName(state: string): string {
  return `onyx:oauth-config-test:result:${state}`;
}
