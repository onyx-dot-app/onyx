"use client";

import useSWR from "swr";

import { UsageLimits, LimitType } from "@/app/craft/types/streamingTypes";

import {
  USAGE_LIMITS_ENDPOINT,
  fetchUsageLimits,
} from "@/app/craft/services/apiServices";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";

// Re-export types for consumers
export type { UsageLimits, LimitType };

// =============================================================================
// Hook Return Type
// =============================================================================

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
// Hook Implementation
// =============================================================================

/**
 * useUsageLimits - Hook for managing build mode usage limits
 *
 * Rate limits from API:
 * - Free/unpaid users: 5 messages total (limitType: "total")
 * - Paid users: 25 messages per week by default (limitType: "weekly")
 *   (configurable via CRAFT_PAID_USER_RATE_LIMIT env var)
 *
 * Only fetches when NEXT_PUBLIC_CLOUD_ENABLED is true.
 * Automatically fetches limits on mount and provides refresh capability.
 */
export function useUsageLimits(): UseUsageLimitsReturn {
  const isEnabled = NEXT_PUBLIC_CLOUD_ENABLED;

  const { data, error, isLoading, mutate } = useSWR<UsageLimits>(
    // Only fetch if cloud is enabled
    isEnabled ? USAGE_LIMITS_ENDPOINT : null,
    fetchUsageLimits,
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

  return {
    limits: data ?? null,
    isLoading,
    error: error ?? null,
    isEnabled,
    refreshLimits: () => mutate(),
  };
}
