"use client";

import { usePostHog } from "posthog-js/react";
import { FeatureFlagKey } from "@/lib/featureFlags";

/**
 * Read a PostHog feature flag value on the client.
 *
 * Wraps `posthog?.isFeatureEnabled(...)` so callers don't have to remember
 * to fall back when PostHog isn't initialized (self-hosted/MIT installs that
 * don't set `NEXT_PUBLIC_POSTHOG_KEY`, local dev without a key, etc.).
 *
 * @param flagKey - Flag key from `FEATURE_FLAGS` (typed; typos are caught).
 * @param defaultValue - Value returned when PostHog is unavailable or the
 *   flag has no resolved value yet. Defaults to `false`. Pass `true` if the
 *   feature should be on by default.
 *
 * @example
 * const showMetrics = useFeatureFlag(FEATURE_FLAGS.INDEX_ATTEMPT_METRICS);
 * if (!showMetrics) return null;
 */
export default function useFeatureFlag(
  flagKey: FeatureFlagKey,
  defaultValue: boolean = false
): boolean {
  const posthog = usePostHog();
  return posthog?.isFeatureEnabled(flagKey) ?? defaultValue;
}
