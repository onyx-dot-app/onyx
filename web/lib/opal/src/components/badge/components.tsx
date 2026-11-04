"use client";

import "@opal/components/badge/styles.css";
import type {
  IconFunctionComponent,
  RichStr,
  StatusVariants,
} from "@opal/types";
import { BADGE_COLORS } from "@opal/components/badge/colors";
import {
  TEXT_COLOR_CLASSES,
  type TextColor,
} from "@opal/components/text/components";
import { Content } from "@opal/layouts";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Height on the Tailwind scale: `4` is 1rem, `6` is 1.5rem. */
type BadgeSize = 4 | 6;

// Takes no DOM attributes. The ref and anything a wrapping Tooltip or
// popover trigger injects at runtime still reach the root, so either can
// wrap a Badge.
type BadgeProps = {
  ref?: React.Ref<HTMLDivElement>;

  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /** Badge label text. */
  title: string | RichStr;

  /**
   * Status color: the tinted background and the icon. Default: `"default"`.
   */
  color?: StatusVariants;

  /**
   * The label's colour. `"inherit"` is the text colour matched to `color`'s
   * background. Default: `"inherit"`.
   */
  textColor?: TextColor;

  /** Height on the Tailwind scale. Default: `4`. */
  size?: BadgeSize;
};

// ---------------------------------------------------------------------------
// Badge
// ---------------------------------------------------------------------------

/**
 * A small coloured label: an icon and a title in a tinted pill. It does
 * nothing on click. For a removable, clickable or field pill, use `Tag`.
 */
function Badge({
  icon,
  title,
  color = "default",
  textColor = "inherit",
  size = 4,
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
        config.bg,
        textColor === "inherit" ? config.text : TEXT_COLOR_CLASSES[textColor]
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

export { Badge, type BadgeProps, type BadgeSize };
export { BADGE_COLORS } from "@opal/components/badge/colors";
