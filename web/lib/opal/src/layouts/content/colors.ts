// Content's text colours, keyed by status. Badge and Tag take theirs from
// here. Kept in a standalone module so non-React surfaces (e.g. the raw-DOM
// tile in richInputTile.ts) can source the same classes without pulling in
// the component/CSS barrel.

import type { StatusColor } from "@opal/types";

/**
 * The colour of a `Content` in each status: the title and icon take it.
 * `text` is the class, `fg` the CSS value. `default` is the neutral `text-04`.
 */
export const CONTENT_STATUS_COLORS: Record<
  StatusColor,
  { text: string; fg: string }
> = {
  default: { text: "text-text-04", fg: "var(--text-04)" },
  info: { text: "text-theme-blue-05", fg: "var(--theme-blue-05)" },
  success: { text: "text-theme-green-05", fg: "var(--theme-green-05)" },
  warning: { text: "text-status-warning-05", fg: "var(--status-warning-05)" },
  pending: { text: "text-theme-amber-05", fg: "var(--theme-amber-05)" },
  queued: { text: "text-theme-purple-05", fg: "var(--theme-purple-05)" },
  error: { text: "text-status-error-05", fg: "var(--status-error-05)" },
};
