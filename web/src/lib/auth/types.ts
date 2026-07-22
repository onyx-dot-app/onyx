// Wire values of the backend session-rejection codes carried in the `/api/me`
// 403 body (`backend/onyx/error_handling/error_codes.py`).
export enum SessionEndReason {
  EXPIRED = "SESSION_EXPIRED",
  TERMINATED = "SESSION_TERMINATED",
  UNRECOGNIZED = "SESSION_UNRECOGNIZED",
}

export type SSOProviderType = "GOOGLE_OAUTH" | "OIDC" | "SAML";

export interface SSOProviderOption {
  name: string;
  displayName: string;
  providerType: SSOProviderType;
  authorizeUrl: string;
}

export interface AuthTypeMetadata {
  multiTenant: boolean;
  requiresVerification: boolean;
  anonymousUserEnabled: boolean | null;
  passwordMinLength: number;
  passwordMaxLength: number;
  passwordRequireUppercase: boolean;
  passwordRequireLowercase: boolean;
  passwordRequireDigit: boolean;
  passwordRequireSpecialChar: boolean;
  hasUsers: boolean;
  oauthEnabled: boolean;
  // Enabled DB-backed SSO providers, one login button each. Empty on cloud
  // and when no provider rows exist.
  ssoProviders?: SSOProviderOption[];
}
