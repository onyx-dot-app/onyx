import { TokenProvider, WidgetConfig } from "@/types/widget-types";

const SHARED_CREDENTIAL_IDENTITY = "shared-credential";

const MISSING_CREDENTIAL_MESSAGE =
  "No Onyx credential available. Set the `api-key` attribute, or assign a " +
  "`tokenProvider` function on the <onyx-chat-widget> element.";

/**
 * Resolve widget configuration from attributes and environment variables
 * Priority: attributes > environment variables > defaults
 */
export function resolveConfig(attributes: Partial<WidgetConfig>): WidgetConfig {
  const config = {
    backendUrl:
      attributes.backendUrl || import.meta.env.VITE_WIDGET_BACKEND_URL || "",
    apiKey: attributes.apiKey || import.meta.env.VITE_WIDGET_API_KEY || "",
    agentId: attributes.agentId,
    primaryColor: attributes.primaryColor,
    backgroundColor: attributes.backgroundColor,
    textColor: attributes.textColor,
    agentName: attributes.agentName || "Assistant",
    logo: attributes.logo,
    mode: attributes.mode || "launcher",
    includeCitations: attributes.includeCitations ?? false,
  };

  if (!config.backendUrl) {
    throw new Error("backendUrl is required for the widget to function");
  }

  return config;
}

/**
 * Pick the credential for one request. A `tokenProvider` wins over `apiKey`.
 * Credentials are resolved here rather than at mount because a host usually
 * assigns `tokenProvider` after the element has already been parsed.
 */
export function resolveAuthToken(
  tokenProvider: TokenProvider | undefined,
  apiKey: string | undefined
): string | Promise<string> {
  if (tokenProvider) {
    return tokenProvider();
  }
  if (apiKey) {
    return apiKey;
  }
  throw new Error(MISSING_CREDENTIAL_MESSAGE);
}

/**
 * Stable identifier for whoever the credential represents, used to scope the
 * stored transcript. A JWT yields its subject, so a second person signing in
 * on the same tab never sees the first person's messages. Anything else is a
 * shared credential, which every visitor already has in common.
 */
export function deriveCredentialIdentity(token: string): string {
  const claims = decodeJwtClaims(token);
  const subject = claims?.sub ?? claims?.email;
  return typeof subject === "string" && subject
    ? subject
    : SHARED_CREDENTIAL_IDENTITY;
}

function decodeJwtClaims(token: string): Record<string, unknown> | null {
  const segments = token.split(".");
  if (segments.length !== 3) {
    return null;
  }

  try {
    const base64 = segments[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(
      base64.length + ((4 - (base64.length % 4)) % 4),
      "="
    );
    const bytes = Uint8Array.from(atob(padded), (char) => char.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return null;
  }
}
