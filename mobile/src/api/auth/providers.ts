import type { AuthType, AuthTypeMetadata } from "@/api/types";

export type ProviderId = "password" | "google" | "oidc" | "saml" | "apple";
export type ProviderKind = "password" | "browser";

export interface ProviderDescriptor {
  id: ProviderId;
  label: string;
  kind: ProviderKind;
  // Relative to the API prefix; unused for `password`.
  authorizePath?: string;
}

export const PROVIDER_REGISTRY: Partial<
  Record<ProviderId, ProviderDescriptor>
> = {
  password: { id: "password", label: "Email", kind: "password" },
  google: {
    id: "google",
    label: "Google",
    kind: "browser",
    // Mobile-only route; its callback returns to the backend, not the web app.
    authorizePath: "/auth/mobile/oauth/authorize",
  },
};

// `cloud` accepts password too (Google + basic).
const PASSWORD_AUTH_TYPES: ReadonlySet<AuthType> = new Set<AuthType>([
  "basic",
  "cloud",
]);

const GOOGLE_AUTH_TYPES: ReadonlySet<AuthType> = new Set<AuthType>([
  "google_oauth",
  "cloud",
]);

// Returns [] until the backend config loads.
export function visibleProviders(
  config: AuthTypeMetadata | undefined,
): ProviderDescriptor[] {
  if (!config) return [];

  const providers: ProviderDescriptor[] = [];
  const password = PROVIDER_REGISTRY.password;
  if (password && PASSWORD_AUTH_TYPES.has(config.auth_type)) {
    providers.push(password);
  }
  const google = PROVIDER_REGISTRY.google;
  if (
    google &&
    config.oauth_enabled &&
    GOOGLE_AUTH_TYPES.has(config.auth_type)
  ) {
    providers.push(google);
  }
  return providers;
}
