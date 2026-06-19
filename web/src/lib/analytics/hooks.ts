"use client";

/**
 * PostHog-specific React hooks and flag registry.
 *
 * Hooks in this file are intentionally named with a `usePH` prefix to make
 * their PostHog dependency explicit at the call site — callers know they are
 * reaching into PostHog rather than a generic feature-flag abstraction.
 */

import { usePostHog } from "posthog-js/react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useSettings } from "@/lib/settings/hooks";
import { EE_ENABLED } from "@/lib/constants";

// ─── Feature Flag Registry ─────────────────────────────────────────────────

/**
 * Centralized PostHog feature flag key registry.
 *
 * Use these enum members instead of inline strings so flag usage is greppable
 * and typos are caught at compile time. To add a new flag, append a new member
 * here and add its default to `PHFeatureFlagDefaults`, then check it via
 * `usePHFeatureFlag`.
 *
 * These flags are evaluated client-side and intentionally trust the browser:
 * they are appropriate for UI rollouts/experiments where it's fine if a
 * savvy user flips the flag for themselves. Flags that must also gate
 * backend behavior should be evaluated server-side and surfaced via the
 * `/api/settings` response instead.
 */
export enum PHFeatureFlag {
  /** Disables the Onyx Craft (Build Mode) sidebar intro animation. */
  CRAFT_ANIMATION_DISABLED = "craft-animation-disabled",
  /** Disables adding or modifying LLM providers on the admin Language Models page. */
  LANGUAGE_MODEL_CONFIGURATION_DISABLED = "language-model-configuration-disabled",
}

/**
 * Default values returned when PostHog is unavailable (e.g. self-hosted
 * installs, local dev without a PostHog key, or before flags have loaded).
 *
 * Each entry must have a key for every member of `PHFeatureFlag`. The default
 * should represent the safe, expected behaviour for users who are not targeted
 * by the flag.
 */
const PHFeatureFlagDefaults: Record<PHFeatureFlag, boolean> = {
  [PHFeatureFlag.CRAFT_ANIMATION_DISABLED]: true,
  [PHFeatureFlag.LANGUAGE_MODEL_CONFIGURATION_DISABLED]: false,
};

// ─── Hooks ─────────────────────────────────────────────────────────────────

/**
 * Read a PostHog feature flag value on the client.
 *
 * Wraps `posthog?.isFeatureEnabled(...)` so callers don't have to handle the
 * case where PostHog isn't initialized — which happens in local dev (no
 * `NEXT_PUBLIC_POSTHOG_KEY` set) and in self-hosted / MIT installs.
 *
 * When PostHog is unavailable or the flag doesn't exist, falls back to the
 * value declared in `PHFeatureFlagDefaults` for that flag.
 *
 * @param flag - A member of `PHFeatureFlag`. Using the enum (rather than a
 *   raw string) ensures typos are caught at compile time and usages are
 *   greppable.
 *
 * @example
 * const animationDisabled = usePHFeatureFlag(PHFeatureFlag.CRAFT_ANIMATION_DISABLED);
 * const configEnabled = usePHFeatureFlag(PHFeatureFlag.LANGUAGE_MODEL_CONFIGURATION_ENABLED);
 */
export function usePHFeatureFlag(flag: PHFeatureFlag): boolean {
  const posthog = usePostHog();
  return posthog?.isFeatureEnabled(flag) ?? PHFeatureFlagDefaults[flag];
}

/**
 * Fetches the admin-configured custom analytics script string.
 *
 * Self-gated on EE availability. Returns `null` when EE is disabled or no
 * script is configured.
 */
export function useCustomAnalyticsScript(): string | null {
  const { isLoading, error, ee_features_enabled } = useSettings();
  const shouldFetch =
    EE_ENABLED || (!isLoading && !error && ee_features_enabled !== false);

  const { data } = useSWR<string>(
    shouldFetch ? SWR_KEYS.customAnalyticsScript : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: false,
      dedupingInterval: 60_000,
    }
  );
  return data ?? null;
}
