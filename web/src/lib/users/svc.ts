import { mutate } from "swr";
import { User, UserPersonalization } from "@/lib/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { CustomRefreshTokenResponse } from "@/lib/users/types";

export function checkUserIsNoAuthUser(userId: string): boolean {
  return userId === "__no_auth_user__";
}

export async function getCurrentUser(): Promise<User | null> {
  const response = await fetch("/api/me", {
    credentials: "include",
  });
  if (!response.ok) {
    return null;
  }
  const user = await response.json();
  return user;
}

export async function logout(): Promise<Response> {
  const response = await fetch("/auth/logout", {
    method: "POST",
    credentials: "include",
  });
  if (response.ok) {
    // Drop the cached /api/me so any subsequent useCurrentUser read does not
    // hand callers the just-signed-out user from the SWR dedup window.
    await mutate(SWR_KEYS.me, null, { revalidate: false });
  }
  return response;
}

export async function basicLogin(
  email: string,
  password: string,
  captchaToken?: string
): Promise<Response> {
  const params = new URLSearchParams([
    ["username", email],
    ["password", password],
  ]);

  const headers: Record<string, string> = {
    "Content-Type": "application/x-www-form-urlencoded",
  };
  if (captchaToken) {
    headers["X-Captcha-Token"] = captchaToken;
  }

  return fetch("/api/auth/login", {
    method: "POST",
    credentials: "include",
    headers,
    body: params,
  });
}

export async function basicSignup(
  email: string,
  password: string,
  referralSource?: string,
  captchaToken?: string
): Promise<Response> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (captchaToken) {
    headers["X-Captcha-Token"] = captchaToken;
  }

  return fetch("/api/auth/register", {
    method: "POST",
    credentials: "include",
    headers,
    body: JSON.stringify({
      email,
      username: email,
      password,
      referral_source: referralSource,
      captcha_token: captchaToken,
    }),
  });
}

export async function refreshToken(
  customRefreshUrl: string
): Promise<CustomRefreshTokenResponse | null> {
  try {
    console.debug("Sending request to custom refresh URL");
    const url = customRefreshUrl.startsWith("http")
      ? new URL(customRefreshUrl)
      : new URL(customRefreshUrl, window.location.origin);
    url.searchParams.append("info", "json");
    url.searchParams.append("access_token_refresh_interval", "3600");

    const response = await fetch(url.toString());
    if (!response.ok) {
      console.error(`Failed to refresh token: ${await response.text()}`);
      return null;
    }

    return await response.json();
  } catch (error) {
    console.error("Error refreshing token:", error);
    throw error;
  }
}

export function getUserDisplayName(user: User | null): string {
  if (user?.personalization?.name) return user.personalization.name;

  if (user?.email) {
    const atIndex = user.email.indexOf("@");
    if (atIndex > 0) {
      return user.email.substring(0, atIndex);
    }
  }

  return "Anonymous";
}

export function getUserEmail(user: User | null): string {
  if (user?.email) return user.email;
  return "anonymous@email.com";
}

/**
 * Derive display initials from a user's name or email.
 *
 * - If a name is provided, uses the first letter of the first two words.
 * - Falls back to the email local part, splitting on `.`, `_`, or `-`.
 * - Returns `null` when no valid alpha initials can be derived.
 */
export function getUserInitials(
  name: string | null,
  email: string
): string | null {
  if (name) {
    const words = name.trim().split(/\s+/);
    if (words.length >= 2) {
      const first = words[0]?.[0];
      const second = words[1]?.[0];
      if (first && second) {
        const result = (first + second).toUpperCase();
        if (/^[A-Z]{2}$/.test(result)) return result;
      }
      return null;
    }
    if (name.trim().length >= 1) {
      const result = name.trim().slice(0, 2).toUpperCase();
      if (/^[A-Z]{1,2}$/.test(result)) return result;
    }
  }

  const local = email.split("@")[0];
  if (!local || local.length === 0) return null;
  const parts = local.split(/[._-]/);
  if (parts.length >= 2) {
    const first = parts[0]?.[0];
    const second = parts[1]?.[0];
    if (first && second) {
      const result = (first + second).toUpperCase();
      if (/^[A-Z]{2}$/.test(result)) return result;
    }
    return null;
  }
  if (local.length >= 2) {
    const result = local.slice(0, 2).toUpperCase();
    if (/^[A-Z]{2}$/.test(result)) return result;
  }
  if (local.length === 1) {
    const result = local.toUpperCase();
    if (/^[A-Z]$/.test(result)) return result;
  }
  return null;
}

export async function setUserDefaultModel(
  model: string | null
): Promise<Response> {
  return fetch(`/api/user/default-model`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ default_model: model }),
  });
}

export async function updateUserPersonalization(
  personalization: Partial<UserPersonalization>
): Promise<Response> {
  return fetch(`/api/user/personalization`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(personalization),
  });
}
