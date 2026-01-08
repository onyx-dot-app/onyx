import { User } from "./types";

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
