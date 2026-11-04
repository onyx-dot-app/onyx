"use client";

import "@opal/components/badge/styles.css";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { BADGE_COLORS, type BadgeColor } from "@opal/components/badge/colors";
import { Content } from "@opal/layouts";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type BadgeSize = "sm" | "md";

/**
 * - `"default"`: tinted background, icon and label in the color's text.
 * - `"status"`: tinted background, icon in the color's text, `text-04` label.
 * - `"count"`: no background, icon in the color's text, `text-04` label.
 */
type BadgeVariant = "default" | "status" | "count";

// Takes no DOM attributes. The ref and anything a wrapping Tooltip or
// popover trigger injects at runtime still reach the root, so either can
// wrap a Badge.
type BadgeProps = {
  ref?: React.Ref<HTMLDivElement>;

  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /** Badge label text. */
  title: string | RichStr;

  /** Color variant. Default: `"gray"`. */
  color?: BadgeColor;

  /** How the color is applied. Default: `"default"`. */
  variant?: BadgeVariant;

  /** Size variant. Default: `"sm"`. */
  size?: BadgeSize;
};

// ---------------------------------------------------------------------------
// Badge
// ---------------------------------------------------------------------------

/**
 * A small coloured label: an icon and a title in a tinted pill. It does
 * nothing on click. For a removable, clickable or field chip, use `Chip`.
 */
function Badge({
  icon,
  title,
  color = "gray",
  variant = "default",
  size = "sm",
  ...rest
}: BadgeProps) {
  const config = BADGE_COLORS[color];

  // SAFETY: CSSProperties has no index for custom properties; the object
  // holds only the one custom property the stylesheet reads.
  const iconColorStyle = {
    "--opal-badge-icon-color": config.fg,
  } as React.CSSProperties;

  return (
    <div
      {...rest}
      className={cn(
        "opal-badge",
        variant !== "count" && config.bg,
        variant === "default" ? config.text : "text-text-04"
      )}
      style={iconColorStyle}
      data-size={size}
    >
      <Content
        // The body variant sets the title in secondary-body.
        sizePreset="secondary"
        variant="body"
        width="fit"
        color="interactive"
        icon={icon}
        title={title}
      />
    </div>
  );
}

export { Badge, type BadgeProps, type BadgeSize, type BadgeVariant };
export { BADGE_COLORS, type BadgeColor } from "@opal/components/badge/colors";
