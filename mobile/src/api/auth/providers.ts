import type { AuthTypeMetadata } from "@/api/types";

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

// Returns [] until the backend config loads.
export function visibleProviders(
  config: AuthTypeMetadata | undefined,
): ProviderDescriptor[] {
  if (!config) return [];

  const providers: ProviderDescriptor[] = [];
  const password = PROVIDER_REGISTRY.password;
  // Every deployment mode serves password login.
  if (password) {
    providers.push(password);
  }
  const google = PROVIDER_REGISTRY.google;
  // The mobile Google OAuth router mounts whenever env credentials exist.
  if (google && config.oauth_enabled) {
    providers.push(google);
  }
  return providers;
}
