import { AuthType } from "@/lib/constants";

export type SSOProviderType = "GOOGLE_OAUTH" | "OIDC" | "SAML";

export interface SSOProviderOption {
  name: string;
  displayName: string;
  providerType: SSOProviderType;
  authorizeUrl: string;
}

export interface AuthTypeMetadata {
  authType: AuthType;
  autoRedirect: boolean;
  requiresVerification: boolean;
  anonymousUserEnabled: boolean | null;
  passwordMinLength: number;
  hasUsers: boolean;
  oauthEnabled: boolean;
  // DB-backed SSO providers, one login button each. Absent on the client-hook
  // path that does not fetch them. The login page treats absent as none.
  ssoProviders?: SSOProviderOption[];
}
