"use client";

/**
 * PostHog-specific React hooks and flag registry.
 *
 * Hooks in this file are intentionally named with a `usePH` prefix to make
 * their PostHog dependency explicit at the call site — callers know they are
 * reaching into PostHog rather than a generic feature-flag abstraction.
 */

import { usePostHog } from "posthog-js/react";
import { IS_DEV } from "@/lib/constants";

// ─── Feature Flag Registry ─────────────────────────────────────────────────

/**
 * Centralized PostHog feature flag key registry.
 *
 * Use these constants instead of inline strings so flag usage is greppable
 * and typos are caught at compile time. To add a new flag, append a new
 * entry here, then check it via `usePHFeatureFlag` (preferred) or
 * `posthog?.isFeatureEnabled(...) ?? <default>` directly.
 *
 * These flags are evaluated client-side and intentionally trust the browser:
 * they are appropriate for UI rollouts/experiments where it's fine if a
 * savvy user flips the flag for themselves. Flags that must also gate
 * backend behavior should be evaluated server-side and surfaced via the
 * `/api/settings` response instead.
 */
export const PHFeatureFlags = {
  /** Disables the Onyx Craft (Build Mode) sidebar intro animation. */
  CRAFT_ANIMATION_DISABLED: "craft-animation-disabled",
  /** Disables adding or modifying LLM providers on the admin Language Models page. */
  LANGUAGE_MODEL_CONFIGURATION_DISABLED:
    "language-model-configuration-disabled",
} as const;

export type FeatureFlagKey =
  (typeof PHFeatureFlags)[keyof typeof PHFeatureFlags];

// ─── Hooks ─────────────────────────────────────────────────────────────────

/**
 * Read a PostHog feature flag value on the client.
 *
 * Wraps `posthog?.isFeatureEnabled(...)` so callers don't have to handle the
 * case where PostHog isn't initialized — which happens in local dev (no
 * `NEXT_PUBLIC_POSTHOG_KEY` set) and in self-hosted / MIT installs.
 *
 * **Default-value convention**
 *
 * When `defaultValue` is omitted and PostHog is unavailable, the hook returns
 * `true` in local dev (`NODE_ENV === "development"`) and `false` elsewhere.
 * This mirrors the backend's `NoOpFeatureFlagProvider`, which returns `True`
 * for `ENVIRONMENT == "local"`, so devs can iterate on flagged features
 * without running PostHog locally.
 *
 * Pass an explicit `defaultValue` when the local-dev default isn't
 * appropriate — for example, a flag that should default to `false` even in
 * dev so that the "disabled" code path can be tested without PostHog:
 *
 * @param flagKey - A key from `PHFeatureFlags` (defined above). Using the
 *   registry constant (rather than a raw string) ensures typos are caught at
 *   compile time and usages are greppable.
 * @param defaultValue - Fallback returned when PostHog is unavailable.
 *   Defaults to `true` in local dev, `false` in all other environments.
 *
 * @example
 * // Use the local-dev default (true in dev, false in prod):
 * const animationDisabled = usePHFeatureFlag(PHFeatureFlags.CRAFT_ANIMATION_DISABLED);
 *
 * @example
 * // Always default to false regardless of environment:
 * const configDisabled = usePHFeatureFlag(
 *   PHFeatureFlags.LANGUAGE_MODEL_CONFIGURATION_DISABLED,
 *   false,
 * );
 */
export function usePHFeatureFlag(
  flagKey: FeatureFlagKey,
  defaultValue: boolean = IS_DEV
): boolean {
  const posthog = usePostHog();
  return posthog?.isFeatureEnabled(flagKey) ?? defaultValue;
}
