// Badge color tints, keyed by status. Kept in a standalone module so non-React
// surfaces (e.g. the raw-DOM skill tile in richInputTile.ts) can source the same
// classes without pulling in the component/CSS barrel.

import type { StatusVariants } from "@opal/types";

// `fg` is the `text` colour as a CSS value, for the badge's icon.
export const BADGE_COLORS: Record<
  StatusVariants,
  { bg: string; text: string; fg: string }
> = {
  default: {
    bg: "bg-background-tint-02",
    text: "text-text-03",
    fg: "var(--text-03)",
  },
  info: {
    bg: "bg-theme-blue-01",
    text: "text-theme-blue-05",
    fg: "var(--theme-blue-05)",
  },
  success: {
    bg: "bg-theme-green-01",
    text: "text-theme-green-05",
    fg: "var(--theme-green-05)",
  },
  warning: {
    bg: "bg-status-warning-01",
    text: "text-status-warning-05",
    fg: "var(--status-warning-05)",
  },
  pending: {
    bg: "bg-theme-amber-01",
    text: "text-theme-amber-05",
    fg: "var(--theme-amber-05)",
  },
  queued: {
    bg: "bg-theme-purple-01",
    text: "text-theme-purple-05",
    fg: "var(--theme-purple-05)",
  },
  error: {
    bg: "bg-status-error-01",
    text: "text-status-error-05",
    fg: "var(--status-error-05)",
  },
};
