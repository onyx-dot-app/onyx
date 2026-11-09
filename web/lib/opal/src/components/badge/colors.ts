// Badge fill tints, keyed by status. The text and icon colours are Content's
// (`CONTENT_STATUS_COLORS`); a badge only adds its fill. Kept in a standalone
// module (it imports only Content's colour table) so non-React surfaces (e.g.
// the raw-DOM skill tile in richInputTile.ts) can source the same classes
// without pulling in the component/CSS barrel.

import { CONTENT_STATUS_COLORS } from "@opal/layouts/content/colors";
import type { StatusColor } from "@opal/types";

export const BADGE_COLORS: Record<StatusColor, { bg: string }> = {
  default: { bg: "bg-background-tint-02" },
  info: { bg: "bg-theme-blue-01" },
  success: { bg: "bg-theme-green-01" },
  warning: { bg: "bg-status-warning-01" },
  pending: { bg: "bg-theme-amber-01" },
  queued: { bg: "bg-theme-purple-01" },
  error: { bg: "bg-status-error-01" },
};

/**
 * A badge's text colour class: Content's status colour, except the neutral
 * default, which a badge mutes to `text-03` on its gray fill.
 */
export function badgeTextClass(color: StatusColor): string {
  return color === "default"
    ? "text-text-03"
    : CONTENT_STATUS_COLORS[color].text;
}
