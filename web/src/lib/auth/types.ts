// Wire values of the backend session-rejection codes carried in the `/api/me`
// 403 body (`backend/onyx/error_handling/error_codes.py`).
export enum SessionEndReason {
  EXPIRED = "SESSION_EXPIRED",
  TERMINATED = "SESSION_TERMINATED",
  UNRECOGNIZED = "SESSION_UNRECOGNIZED",
}

// Error body of the fastapi-users routes (`fastapi_users.router.common.ErrorModel`).
// The register and reset-password routes send an object when the password is
// invalid.
export interface FastApiUsersErrorBody {
  detail?: string | { code: string; reason: string };
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
  // Admin kill switch (single-tenant). False hides password login and signup.
  passwordAuthEnabled: boolean;
  // Enabled DB-backed SSO providers, one login button each. Empty on cloud
  // and when no provider rows exist.
  ssoProviders?: SSOProviderOption[];
}
