import type { OAuthProviderDecision } from "@/lib/oauth-provider/types";

export async function submitOAuthProviderConsent(
  requestId: string,
  csrfToken: string,
  decision: OAuthProviderDecision
): Promise<string> {
  const response: Response = await fetch("/api/oauth-provider/consent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      request_id: requestId,
      csrf_token: csrfToken,
      decision,
    }),
  });
  if (!response.ok) throw new Error("OAuth provider consent failed");

  const payload: unknown = await response.json();
  if (
    !payload ||
    typeof payload !== "object" ||
    !("redirect_url" in payload) ||
    typeof payload.redirect_url !== "string"
  ) {
    throw new Error("Invalid OAuth provider consent response");
  }

  const target: URL = new URL(payload.redirect_url);
  const localHttp: boolean =
    target.protocol === "http:" &&
    ["localhost", "127.0.0.1", "[::1]"].includes(target.hostname);
  if (
    (target.protocol !== "https:" && !localHttp) ||
    target.username ||
    target.password
  ) {
    throw new Error("Invalid OAuth provider callback");
  }

  return target.toString();
}
