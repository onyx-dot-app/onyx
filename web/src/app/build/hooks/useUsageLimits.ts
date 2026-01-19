"use client";

import useSWR from "swr";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
// TODO: Use errorHandlingFetcher when API is ready
// import { errorHandlingFetcher } from "@/lib/fetcher";

// =============================================================================
// Types - Define these now so components know what to expect
// =============================================================================

export type LimitType = "weekly" | "total";

export interface UsageLimits {
  /** Whether the user has reached their limit */
  isLimited: boolean;
  /** Type of limit period: "weekly" for paid, "total" for free */
  limitType: LimitType;
  /** Number of messages used in current period */
  messagesUsed: number;
  /** Maximum messages allowed in the period */
  limit: number;
  /** For weekly limits: timestamp when the limit resets (null for total limits) */
  resetTimestamp: Date | null;
}

// API response shape (snake_case from backend)
interface UsageLimitsResponse {
  is_limited: boolean;
  limit_type: LimitType;
  messages_used: number;
  limit: number;
  reset_timestamp: string | null;
}

export interface UseUsageLimitsReturn {
  // Limits state
  limits: UsageLimits | null;
  isLoading: boolean;
  error: Error | null;
  /** Whether limits are enabled (cloud mode) */
  isEnabled: boolean;

  // Actions
  refreshLimits: () => void;
}

// =============================================================================
// Transform API response to frontend types
// =============================================================================

function transformResponse(data: UsageLimitsResponse): UsageLimits {
  return {
    isLimited: data.is_limited,
    limitType: data.limit_type,
    messagesUsed: data.messages_used,
    limit: data.limit,
    resetTimestamp: data.reset_timestamp
      ? new Date(data.reset_timestamp)
      : null,
  };
}

// =============================================================================
// Mock fetcher for development (remove when API is ready)
// =============================================================================

const mockFetcher = async (): Promise<UsageLimitsResponse> => {
  // Simulate network delay
  await new Promise((resolve) => setTimeout(resolve, 100));

  // Return mock data
  return {
    is_limited: false,
    limit_type: "total",
    messages_used: 1,
    limit: 10,
    reset_timestamp: null,
  };
};

// =============================================================================
// Hook Implementation
// =============================================================================

/**
 * useUsageLimits - Hook for managing build mode usage limits
 *
 * Rate limits from API:
 * - Free/unpaid users: 10 messages total (limitType: "total")
 * - Paid users: 50 messages per week (limitType: "weekly")
 *
 * Only fetches when NEXT_PUBLIC_CLOUD_ENABLED is true.
 * Automatically fetches limits on mount and provides refresh capability.
 *
 * API endpoint: GET /api/build/limit
 */
export function useUsageLimits(): UseUsageLimitsReturn {
  // TODO: Remove this once API is ready
  // const isEnabled = NEXT_PUBLIC_CLOUD_ENABLED;
  const isEnabled = true;
  const { data, error, isLoading, mutate } = useSWR<UsageLimitsResponse>(
    // Only fetch if cloud is enabled
    isEnabled ? "/api/build/limit" : null,
    // TODO: Replace mockFetcher with errorHandlingFetcher when API is ready
    mockFetcher,
    {
      // Revalidate on focus (when user returns to tab)
      revalidateOnFocus: true,
      // Revalidate on reconnect
      revalidateOnReconnect: true,
      // No caching - usage changes with every message sent
      // Callers should call refreshLimits() after sending messages
      dedupingInterval: 0,
    }
  );

  const limits = data ? transformResponse(data) : null;

  return {
    limits,
    isLoading,
    error: error ?? null,
    isEnabled,
    refreshLimits: () => mutate(),
  };
}
