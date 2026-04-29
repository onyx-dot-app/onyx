/**
 * Centralized PostHog feature flag key registry.
 *
 * Use these constants instead of inline strings so flag usage is greppable
 * and typos are caught at compile time. To add a new flag, append a new
 * entry here, then check it via `useFeatureFlag` (preferred) or
 * `posthog?.isFeatureEnabled(...) ?? <default>` directly.
 *
 * These flags are evaluated client-side and intentionally trust the browser:
 * they are appropriate for UI rollouts/experiments where it's fine if a
 * savvy user flips the flag for themselves. Flags that must also gate
 * backend behavior should be evaluated server-side and surfaced via the
 * `/api/settings` response instead — see `web/AGENTS.md` (or ask).
 */
export const FEATURE_FLAGS = {
  /** Disables the Onyx Craft (Build Mode) sidebar intro animation. */
  CRAFT_ANIMATION_DISABLED: "craft-animation-disabled",
  /** Enables the per-index-attempt stage metrics UI (admin connector page). */
  INDEX_ATTEMPT_METRICS: "index-attempt-metrics",
} as const;

export type FeatureFlagKey = (typeof FEATURE_FLAGS)[keyof typeof FEATURE_FLAGS];
