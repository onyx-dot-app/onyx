import { buildUrl, UrlBuilder } from "@/lib/utilsSS";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { User, UserRole } from "@/lib/types";
import { getCurrentUserSS } from "@/lib/users/svcSS";
import {
  AuthType,
  AuthTypeMetadata,
  type SSOProviderType,
} from "@/lib/auth/types";

export async function getAuthTypeMetadataSS(): Promise<AuthTypeMetadata> {
  const res = await fetch(buildUrl("/auth/type"));
  if (!res.ok) {
    throw new Error("Failed to fetch data");
  }

  const data: {
    auth_type: string;
    requires_verification: boolean;
    anonymous_user_enabled: boolean | null;
    password_min_length: number;
    has_users: boolean;
    oauth_enabled: boolean;
    sso_providers?: {
      name: string;
      display_name: string;
      provider_type: SSOProviderType;
      authorize_url: string;
    }[];
  } = await res.json();

  const authType: AuthType = NEXT_PUBLIC_CLOUD_ENABLED
    ? AuthType.CLOUD
    : (data.auth_type as AuthType);

  return {
    authType,
    // for SAML / OIDC, we auto-redirect the user to the IdP when the user visits
    // Onyx in an un-authenticated state
    autoRedirect: authType === AuthType.OIDC || authType === AuthType.SAML,
    requiresVerification: data.requires_verification,
    anonymousUserEnabled: data.anonymous_user_enabled,
    passwordMinLength: data.password_min_length,
    hasUsers: data.has_users,
    oauthEnabled: data.oauth_enabled,
    ssoProviders: (data.sso_providers ?? []).map((provider) => ({
      name: provider.name,
      displayName: provider.display_name,
      providerType: provider.provider_type,
      authorizeUrl: provider.authorize_url,
    })),
  };
}

async function getOIDCAuthUrlSS(nextUrl: string | null): Promise<string> {
  const url = UrlBuilder.fromClientUrl("/api/auth/oidc/authorize");
  if (nextUrl) url.addParam("next", nextUrl);
  url.addParam("redirect", true);
  return url.toString();
}

async function getGoogleOAuthUrlSS(nextUrl: string | null): Promise<string> {
  const url = UrlBuilder.fromClientUrl("/api/auth/oauth/authorize");
  if (nextUrl) url.addParam("next", nextUrl);
  url.addParam("redirect", true);
  return url.toString();
}

async function getSAMLAuthUrlSS(nextUrl: string | null): Promise<string> {
  const url = UrlBuilder.fromInternalUrl("/auth/saml/authorize");
  if (nextUrl) url.addParam("next", nextUrl);

  const res = await fetch(url.toString());
  if (!res.ok) throw new Error("Failed to fetch data");

  const data: { authorization_url: string } = await res.json();
  return data.authorization_url;
}

export async function getAuthUrlSS(
  authType: AuthType,
  nextUrl: string | null
): Promise<string> {
  switch (authType) {
    case AuthType.BASIC:
      return "";
    case AuthType.GOOGLE_OAUTH:
    case AuthType.CLOUD:
      return getGoogleOAuthUrlSS(nextUrl);
    case AuthType.SAML:
      return getSAMLAuthUrlSS(nextUrl);
    case AuthType.OIDC:
      return getOIDCAuthUrlSS(nextUrl);
  }
}

async function logoutStandardSS(headers: Headers): Promise<Response> {
  return fetch(buildUrl("/auth/logout"), { method: "POST", headers });
}

async function logoutSAMLSS(headers: Headers): Promise<Response> {
  return fetch(buildUrl("/auth/saml/logout"), { method: "POST", headers });
}

export async function logoutSS(
  authType: AuthType,
  headers: Headers
): Promise<Response | null> {
  switch (authType) {
    case AuthType.SAML:
      return logoutSAMLSS(headers);
    default:
      return logoutStandardSS(headers);
  }
}

// ---------------------------------------------------------------------------
// Auth guards
// ---------------------------------------------------------------------------

interface AuthCheckResult {
  user: User | null;
  authTypeMetadata: AuthTypeMetadata | null;
  redirect?: string;
}

const ADMIN_ALLOWED_ROLES = [
  UserRole.ADMIN,
  UserRole.CURATOR,
  UserRole.GLOBAL_CURATOR,
];

export async function requireAuth(): Promise<AuthCheckResult> {
  let user: User | null = null;
  let authTypeMetadata: AuthTypeMetadata | null = null;

  try {
    [authTypeMetadata, user] = await Promise.all([
      getAuthTypeMetadataSS(),
      getCurrentUserSS(),
    ]);
  } catch (e) {
    console.log(`Failed to fetch auth information - ${e}`);
  }

  if (!user) {
    return { user, authTypeMetadata, redirect: "/auth/login" };
  }

  if (user && !user.is_verified && authTypeMetadata?.requiresVerification) {
    return {
      user,
      authTypeMetadata,
      redirect: "/auth/waiting-on-verification",
    };
  }

  return { user, authTypeMetadata };
}

export async function requireAdminAuth(): Promise<AuthCheckResult> {
  const authResult = await requireAuth();

  if (authResult.redirect) {
    return authResult;
  }

  const { user, authTypeMetadata } = authResult;

  if (user && !ADMIN_ALLOWED_ROLES.includes(user.role)) {
    return { user, authTypeMetadata, redirect: "/app" };
  }

  return authResult;
}
