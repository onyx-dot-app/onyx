export enum AuthType {
  BASIC = "basic",
  GOOGLE_OAUTH = "google_oauth",
  OIDC = "oidc",
  SAML = "saml",
  CLOUD = "cloud",
}

export interface AuthTypeMetadata {
  authType: AuthType;
  autoRedirect: boolean;
  requiresVerification: boolean;
  anonymousUserEnabled: boolean | null;
  passwordMinLength: number;
  hasUsers: boolean;
  oauthEnabled: boolean;
}
