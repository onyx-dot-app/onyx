"use client";

import { usePostHog } from "posthog-js/react";
import { FeatureFlagKey } from "@/lib/featureFlags";
import { IS_DEV } from "@/lib/constants";

/**
 * Read a PostHog feature flag value on the client.
 *
 * Wraps `posthog?.isFeatureEnabled(...)` so callers don't have to remember
 * to fall back when PostHog isn't initialized — that's the case in local
 * dev (no `NEXT_PUBLIC_POSTHOG_KEY` set) and in self-hosted/MIT installs.
 *
 * **Local-dev convention**: when no `defaultValue` is passed and PostHog is
 * unavailable, this returns `true` in local dev (`NODE_ENV === "development"`)
 * and `false` everywhere else. This mirrors the backend's
 * `NoOpFeatureFlagProvider`, which returns `True` for `ENVIRONMENT == "local"`,
 * so devs can iterate on flagged features without standing up PostHog.
 *
 * @param flagKey - Flag key from `FEATURE_FLAGS` (typed; typos are caught).
 * @param defaultValue - Override the fallback used when PostHog is
 *   unavailable. Pass an explicit value when the local-dev default isn't
 *   what you want (e.g. you want a flag to default to `true` even in prod
 *   when PostHog is unavailable).
 *
 * @example
 * // On in dev, off in prod-without-PostHog, otherwise PostHog-driven.
 * const showMetrics = useFeatureFlag(FEATURE_FLAGS.INDEX_ATTEMPT_METRICS);
 *
 * @example
 * // Force `true` as the fallback regardless of environment.
 * const animationDisabled = useFeatureFlag(
 *   FEATURE_FLAGS.CRAFT_ANIMATION_DISABLED,
 *   true,
 * );
 */
export default function useFeatureFlag(
  flagKey: FeatureFlagKey,
  defaultValue: boolean = IS_DEV
): boolean {
  const posthog = usePostHog();
  return posthog?.isFeatureEnabled(flagKey) ?? defaultValue;
}
