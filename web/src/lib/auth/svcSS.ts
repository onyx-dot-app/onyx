import "server-only";

import { buildUrl, UrlBuilder } from "@/lib/utilsSS";
import { getDomain } from "@/lib/redirectSS";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { NextRequest, NextResponse } from "next/server";
import { AuthTypeMetadata, type SSOProviderType } from "@/lib/auth/types";
import { User, UserRole } from "@/lib/types";
import { getCurrentUserSS } from "@/lib/users/svcSS";

export async function getAuthTypeMetadataSS(): Promise<AuthTypeMetadata> {
  const res = await fetch(buildUrl("/auth/type"));
  if (!res.ok) {
    throw new Error("Failed to fetch data");
  }

  const data: {
    multi_tenant: boolean;
    requires_verification: boolean;
    anonymous_user_enabled: boolean | null;
    password_min_length: number;
    password_max_length: number;
    password_require_uppercase: boolean;
    password_require_lowercase: boolean;
    password_require_digit: boolean;
    password_require_special_char: boolean;
    has_users: boolean;
    oauth_enabled: boolean;
    sso_providers?: {
      name: string;
      display_name: string;
      provider_type: SSOProviderType;
      authorize_url: string;
    }[];
  } = await res.json();

  const multiTenant: boolean = NEXT_PUBLIC_CLOUD_ENABLED
    ? true
    : data.multi_tenant;

  return {
    multiTenant,
    requiresVerification: data.requires_verification,
    anonymousUserEnabled: data.anonymous_user_enabled,
    passwordMinLength: data.password_min_length,
    passwordMaxLength: data.password_max_length,
    passwordRequireUppercase: data.password_require_uppercase,
    passwordRequireLowercase: data.password_require_lowercase,
    passwordRequireDigit: data.password_require_digit,
    passwordRequireSpecialChar: data.password_require_special_char,
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

async function getGoogleOAuthUrlSS(nextUrl: string | null): Promise<string> {
  const url = UrlBuilder.fromClientUrl("/api/auth/oauth/authorize");
  if (nextUrl) url.addParam("next", nextUrl);
  url.addParam("redirect", true);
  return url.toString();
}

export async function getAuthUrlSS(
  multiTenant: boolean,
  nextUrl: string | null
): Promise<string> {
  return multiTenant ? getGoogleOAuthUrlSS(nextUrl) : "";
}

async function logoutStandardSS(headers: Headers): Promise<Response> {
  return fetch(buildUrl("/auth/logout"), { method: "POST", headers });
}

export async function logoutSS(headers: Headers): Promise<Response | null> {
  return logoutStandardSS(headers);
}

export async function authErrorRedirect(
  request: NextRequest,
  response: Response,
  redirectStatus?: number
): Promise<NextResponse> {
  const errorUrl = new URL("/auth/error", getDomain(request));
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string" && detail) {
      errorUrl.searchParams.set("error", detail);
    }
  } catch {
    // response may not be JSON
  }
  return NextResponse.redirect(errorUrl, redirectStatus);
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
