import { TokenRateLimitArgs } from "./types";

const API_PREFIX = "/api/admin/token-rate-limits";

// Global Token Limits
export const insertGlobalTokenRateLimit = async (
  tokenRateLimit: TokenRateLimitArgs
) => {
  return await fetch(`${API_PREFIX}/global`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(tokenRateLimit),
  });
};

// User Token Limits
export const insertUserTokenRateLimit = async (
  tokenRateLimit: TokenRateLimitArgs
) => {
  return await fetch(`${API_PREFIX}/users`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(tokenRateLimit),
  });
};

// User Group Token Limits (EE Only)
export const insertGroupTokenRateLimit = async (
  tokenRateLimit: TokenRateLimitArgs,
  group_id: number
) => {
  return await fetch(`${API_PREFIX}/user-group/${group_id}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(tokenRateLimit),
  });
};

// Common Endpoints

export const deleteTokenRateLimit = async (token_rate_limit_id: number) => {
  return await fetch(`${API_PREFIX}/rate-limit/${token_rate_limit_id}`, {
    method: "DELETE",
  });
};

export const updateTokenRateLimit = async (
  token_rate_limit_id: number,
  tokenRateLimit: TokenRateLimitArgs
) => {
  return await fetch(`${API_PREFIX}/rate-limit/${token_rate_limit_id}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(tokenRateLimit),
  });
};
