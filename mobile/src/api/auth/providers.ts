// Single source of truth for sign-in methods; adding a provider is a one-line addition here.
import type { AuthType, AuthTypeMetadata } from "@/api/types";

export type ProviderId = "password" | "google" | "oidc" | "saml" | "apple";
export type ProviderKind = "password" | "browser";

export interface ProviderDescriptor {
  id: ProviderId;
  label: string;
  kind: ProviderKind;
  // Backend authorize endpoint for browser-SSO redirects; unused for `password`.
  authorizePath?: string;
}

export const PROVIDER_REGISTRY: Partial<
  Record<ProviderId, ProviderDescriptor>
> = {
  password: { id: "password", label: "Email", kind: "password" },
};

// `cloud` accepts password too (Google + basic).
const PASSWORD_AUTH_TYPES: ReadonlySet<AuthType> = new Set<AuthType>([
  "basic",
  "cloud",
]);

// Filtered by the backend's reported config; returns [] until config loads.
export function visibleProviders(
  config: AuthTypeMetadata | undefined,
): ProviderDescriptor[] {
  if (!config) return [];

  const providers: ProviderDescriptor[] = [];
  const password = PROVIDER_REGISTRY.password;
  if (password && PASSWORD_AUTH_TYPES.has(config.auth_type)) {
    providers.push(password);
  }
  return providers;
}
