import { User } from "@/lib/types";

export const checkUserIsNoAuthUser = (userId: string) => {
  return userId === "__no_auth_user__";
};

export const getCurrentUser = async (): Promise<User | null> => {
  const response = await fetch("/api/me", {
    credentials: "include",
  });
  if (!response.ok) {
    return null;
  }
  const user = await response.json();
  return user;
};

export const logout = async (): Promise<Response> => {
  const response = await fetch("/auth/logout", {
    method: "POST",
    credentials: "include",
  });
  return response;
};

export const basicLogin = async (
  email: string,
  password: string
): Promise<Response> => {
  const params = new URLSearchParams([
    ["username", email],
    ["password", password],
  ]);

  const response = await fetch("/api/auth/login", {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: params,
  });
  return response;
};

export const basicSignup = async (
  email: string,
  password: string,
  referralSource?: string,
  captchaToken?: string
) => {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  // Add captcha token to headers if provided
  if (captchaToken) {
    headers["X-Captcha-Token"] = captchaToken;
  }

  const response = await fetch("/api/auth/register", {
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
  return response;
};

export interface CustomRefreshTokenResponse {
  access_token: string;
  refresh_token: string;
  session: {
    exp: number;
  };
  userinfo: {
    sub: string;
    familyName: string;
    givenName: string;
    fullName: string;
    userId: string;
    email: string;
  };
}

export async function refreshToken(
  customRefreshUrl: string
): Promise<CustomRefreshTokenResponse | null> {
  try {
    console.debug("Sending request to custom refresh URL");
    // support both absolute and relative
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
  // Prioritize custom personal name, if set.
  if (!!user?.personalization?.name) return user.personalization.name;

  // Then, prioritize personal email.
  if (!!user?.email) {
    const atIndex = user.email.indexOf("@");
    if (atIndex > 0) {
      return user.email.substring(0, atIndex);
    }
  }

  // If nothing works, then fall back to anonymous user name
  return "Anonymous";
}

export function getUserEmail(user: User | null): string {
  // Prioritize personal email.
  if (!!user?.email) return user.email;

  // If nothing works, then fall back to anonymous email.
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
