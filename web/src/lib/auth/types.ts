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
