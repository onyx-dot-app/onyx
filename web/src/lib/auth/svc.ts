import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { AuthTypeMetadata, type SSOProviderType } from "@/lib/auth/types";
import type { ErrorResponseBody } from "@/lib/fetcher";

interface AuthTypeAPIResponse {
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
  password_auth_enabled?: boolean;
  sso_providers?: {
    name: string;
    display_name: string;
    provider_type: SSOProviderType;
    authorize_url: string;
  }[];
}

export async function fetchAuthTypeMetadata(
  url: string
): Promise<AuthTypeMetadata> {
  const res = await fetch(url);
  if (!res.ok) {
    console.error(`fetchAuthTypeMetadata: ${res.status} ${res.statusText}`);
    throw new Error("Failed to fetch auth type metadata");
  }
  const data: AuthTypeAPIResponse = await res.json();
  const multiTenant = NEXT_PUBLIC_CLOUD_ENABLED ? true : data.multi_tenant;
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
    passwordAuthEnabled: data.password_auth_enabled ?? true,
    ssoProviders: (data.sso_providers ?? []).map((provider) => ({
      name: provider.name,
      displayName: provider.display_name,
      providerType: provider.provider_type,
      authorizeUrl: provider.authorize_url,
    })),
  };
}

export async function requestEmailVerification(email: string): Promise<void> {
  const response = await fetch("/api/auth/request-verify-token", {
    headers: { "Content-Type": "application/json" },
    method: "POST",
    body: JSON.stringify({ email }),
  });

  if (!response.ok) {
    const error: ErrorResponseBody = await response.json().catch((e) => {
      console.warn(
        "requestEmailVerification: failed to parse error response",
        e
      );
      return {};
    });
    throw new Error(error?.detail || "Failed to request email verification.");
  }
}

export async function verifyCaptchaForOAuth(token: string): Promise<void> {
  const response = await fetch("/api/auth/captcha/oauth-verify", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });

  if (!response.ok) {
    const body: ErrorResponseBody = await response.json().catch((e) => {
      console.warn("verifyCaptchaForOAuth: failed to parse error response", e);
      return {};
    });
    throw new Error(
      `Captcha verify rejected: status=${response.status} detail=${body.detail ?? "(none)"}`
    );
  }
}
