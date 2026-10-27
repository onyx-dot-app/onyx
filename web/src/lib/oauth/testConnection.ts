export const OAUTH_TEST_ACTIVE_KEY = "onyx:oauth-config-test:active";
const TEST_KEY_PREFIX = "onyx:oauth-config-test:attempt:";
export const OAUTH_TEST_MESSAGE_TYPE = "onyx:oauth-config-test-result";

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

export function isOAuthTestMessage(value: unknown): value is OAuthTestMessage {
  if (
    !value ||
    typeof value !== "object" ||
    !("type" in value) ||
    value.type !== OAUTH_TEST_MESSAGE_TYPE ||
    !("state" in value) ||
    typeof value.state !== "string" ||
    !("result" in value)
  )
    return false;

  const result = value.result;
  if (!result || typeof result !== "object" || !("status" in result))
    return false;
  if (result.status === "success") {
    return (
      "supports_pkce" in result && typeof result.supports_pkce === "boolean"
    );
  }
  return ["failed", "denied", "interrupted"].some(
    (status) => status === result.status
  );
}

export function oauthTestChannelName(state: string): string {
  return `onyx:oauth-config-test:result:${state}`;
}
