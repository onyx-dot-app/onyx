"use client";

import "@opal/components/badge/styles.css";
import type { IconFunctionComponent, RichStr, StatusColor } from "@opal/types";
import { BADGE_COLORS } from "@opal/components/badge/colors";
import type { TextColor } from "@opal/components/text/components";
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
  color?: StatusColor;

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
  return (
    <div
      {...rest}
      className={cn("opal-badge", BADGE_COLORS[color].bg)}
      data-size={size}
    >
      <Content
        // The title font sets the height: a 12px line in the small badge,
        // 16px in the large one.
        {...(size === 4
          ? { font: "figure-small-value" as const }
          : { font: "secondary-body" as const })}
        width="fit"
        // Content owns the status colours; a neutral badge mutes to text-03.
        color={color}
        titleColor={
          textColor !== "inherit"
            ? textColor
            : color === "default"
              ? "text-03"
              : undefined
        }
        icon={icon}
        title={title}
      />
    </div>
  );
}

export { Badge, type BadgeProps, type BadgeSize };
export { BADGE_COLORS, badgeTextClass } from "@opal/components/badge/colors";
