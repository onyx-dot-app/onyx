import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { AuthType, AuthTypeMetadata } from "@/lib/auth/types";

interface AuthTypeAPIResponse {
  auth_type: string;
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
}

export const DEFAULT_AUTH_TYPE_METADATA: AuthTypeMetadata = {
  authType: NEXT_PUBLIC_CLOUD_ENABLED ? AuthType.CLOUD : AuthType.BASIC,
  autoRedirect: false,
  requiresVerification: false,
  anonymousUserEnabled: null,
  passwordMinLength: 8,
  passwordMaxLength: 64,
  passwordRequireUppercase: false,
  passwordRequireLowercase: false,
  passwordRequireDigit: false,
  passwordRequireSpecialChar: false,
  hasUsers: false,
  oauthEnabled: false,
};

export async function fetchAuthTypeMetadata(
  url: string
): Promise<AuthTypeMetadata> {
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch auth type metadata");
  const data: AuthTypeAPIResponse = await res.json();
  const authType = NEXT_PUBLIC_CLOUD_ENABLED
    ? AuthType.CLOUD
    : (data.auth_type as AuthType);
  return {
    authType,
    autoRedirect: authType === AuthType.OIDC || authType === AuthType.SAML,
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
  };
}

export async function forgotPassword(email: string): Promise<void> {
  const response = await fetch(`/api/auth/forgot-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });

  if (!response.ok) {
    const error = await response.json();
    const errorMessage =
      error?.detail || "An error occurred during password reset.";
    throw new Error(errorMessage);
  }
}

export async function resetPassword(
  token: string,
  password: string
): Promise<void> {
  const response = await fetch(`/api/auth/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, password }),
  });

  if (!response.ok) {
    const error = await response.json();
    if (error?.detail?.code === "RESET_PASSWORD_INVALID_PASSWORD") {
      throw new Error(error.detail.reason || "Invalid password");
    }
    const errorMessage =
      error?.detail || "An error occurred during password reset.";
    throw new Error(errorMessage);
  }
}

export async function requestEmailVerification(
  email: string
): Promise<Response> {
  return fetch("/api/auth/request-verify-token", {
    headers: { "Content-Type": "application/json" },
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export async function verifyEmail(token: string): Promise<void> {
  const response = await fetch("/api/auth/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });

  if (!response.ok) {
    let detail = "unknown error";
    try {
      detail = (await response.json()).detail;
    } catch {
      // ignore parse failure
    }
    throw new Error(detail);
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
    const body = await response.json().catch(() => ({}));
    throw new Error(
      `Captcha verify rejected: status=${response.status} detail=${body.detail ?? "(none)"}`
    );
  }
}

export async function impersonateUser(
  email: string,
  apiKey: string
): Promise<void> {
  const response = await fetch("/api/tenants/impersonate", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({ email }),
    credentials: "same-origin",
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error?.detail || "Failed to impersonate user");
  }
}
