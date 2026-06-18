// Provider registry — the single source of truth for which sign-in methods the
// login screen renders. Each descriptor is either a `password` (email/password
// form) or a `browser` provider (system-browser OAuth, wired in PR5). Keeping
// the list here means adding Google / OIDC / SAML / Apple later is a one-line
// addition plus a backend branch, not a screen rewrite.
import type { AuthType, AuthTypeMetadata } from "@/api/types";

export type ProviderId = "password" | "google" | "oidc" | "saml" | "apple";
export type ProviderKind = "password" | "browser";

export interface ProviderDescriptor {
  id: ProviderId;
  label: string;
  kind: ProviderKind;
  // Browser providers redirect through the system browser to this backend
  // authorize endpoint. Unused for `password`. (Consumed by browserSso in PR5.)
  authorizePath?: string;
}

// V1 ships only email/password. Browser-SSO descriptors (google, …) are added in
// PR5 alongside browserSso.ts.
export const PROVIDER_REGISTRY: Partial<
  Record<ProviderId, ProviderDescriptor>
> = {
  password: { id: "password", label: "Email", kind: "password" },
};

// AUTH_TYPEs that accept email/password credentials. `cloud` = Google + basic.
const PASSWORD_AUTH_TYPES: ReadonlySet<AuthType> = new Set<AuthType>([
  "basic",
  "cloud",
]);

// Providers to render on the login screen, filtered by the connected backend's
// reported configuration (`/api/auth/type`). Returns [] until config loads.
export function visibleProviders(
  config: AuthTypeMetadata | undefined,
): ProviderDescriptor[] {
  if (!config) return [];

  const providers: ProviderDescriptor[] = [];
  const password = PROVIDER_REGISTRY.password;
  if (password && PASSWORD_AUTH_TYPES.has(config.auth_type)) {
    providers.push(password);
  }
  // Browser-SSO providers (filtered by `config.oauth_enabled`) land in PR5.
  return providers;
}
