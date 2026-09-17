import { parseErrorDetail } from "@/lib/fetcher";
import { TokenRateLimitArgs } from "./types";

const API_PREFIX = "/api/admin/token-rate-limits";
const CREATE_ERROR_MESSAGE = "Failed to create token rate limit";
const UPDATE_ERROR_MESSAGE = "Failed to update token rate limit";
const DELETE_ERROR_MESSAGE = "Failed to delete token rate limit";

// Global Token Limits
export const insertGlobalTokenRateLimit = async (
  tokenRateLimit: TokenRateLimitArgs
): Promise<void> => {
  const response = await fetch(`${API_PREFIX}/global`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(tokenRateLimit),
  });
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response, CREATE_ERROR_MESSAGE));
  }
};

// User Token Limits
export const insertUserTokenRateLimit = async (
  tokenRateLimit: TokenRateLimitArgs
): Promise<void> => {
  const response = await fetch(`${API_PREFIX}/users`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(tokenRateLimit),
  });
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response, CREATE_ERROR_MESSAGE));
  }
};

// User Group Token Limits (EE Only)
export const insertGroupTokenRateLimit = async (
  tokenRateLimit: TokenRateLimitArgs,
  group_id: number
): Promise<void> => {
  const response = await fetch(`${API_PREFIX}/user-group/${group_id}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(tokenRateLimit),
  });
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response, CREATE_ERROR_MESSAGE));
  }
};

// Common Endpoints

export const deleteTokenRateLimit = async (
  token_rate_limit_id: number
): Promise<void> => {
  const response = await fetch(
    `${API_PREFIX}/rate-limit/${token_rate_limit_id}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response, DELETE_ERROR_MESSAGE));
  }
};

export const updateTokenRateLimit = async (
  token_rate_limit_id: number,
  tokenRateLimit: TokenRateLimitArgs
): Promise<void> => {
  const response = await fetch(
    `${API_PREFIX}/rate-limit/${token_rate_limit_id}`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(tokenRateLimit),
    }
  );
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response, UPDATE_ERROR_MESSAGE));
  }
};
