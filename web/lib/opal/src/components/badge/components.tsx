"use client";

import "@opal/components/badge/styles.css";
import type { IconFunctionComponent, RichStr, StatusColor } from "@opal/types";
import { BADGE_COLORS } from "@opal/components/badge/colors";
import { Tooltip } from "@opal/components/tooltip/components";
import type { TextColor } from "@opal/components/text/components";
import { Content } from "@opal/layouts";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Height on the Tailwind scale: `4` is 1rem, `5` is 1.25rem, `6` is 1.5rem. */
type BadgeSize = 4 | 5 | 6;

// Takes no DOM attributes. The ref and anything a popover trigger injects at
// runtime still reach the root, so one can wrap a Badge. For a tooltip, use
// the `tooltip` prop: a wrapping Tooltip nests inside the title's own.
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
   * Overrides the label's colour, as on `Content`: the icon keeps `color`'s,
   * except on `"default"`, where it follows. Unset, the label is `color`'s
   * text colour (`text-03` on the neutral badge).
   */
  titleColor?: Exclude<TextColor, "inherit">;

  /** Height on the Tailwind scale. Default: `4`. */
  size?: BadgeSize;

  /**
   * A tooltip on every hover. It replaces the full-title tooltip, so a cut
   * title shows only this. Use it instead of wrapping the badge in a
   * `Tooltip`.
   */
  tooltip?: string | RichStr;
};

// ---------------------------------------------------------------------------
// Badge
// ---------------------------------------------------------------------------

/**
 * A small coloured label: an icon and a title in a tinted pill. The title
 * is always one line, capped at 10rem with an ellipsis. It does
 * nothing on click. For a removable, clickable or field pill, use `Tag`.
 */
function Badge({
  icon,
  title,
  color = "default",
  titleColor,
  size = 4,
  tooltip,
  ...rest
}: BadgeProps) {
  const badge = (
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
        titleColor={titleColor ?? (color === "default" ? "text-03" : undefined)}
        icon={icon}
        title={title}
        titleMaxLines={1}
        // A custom tooltip covers the whole badge, so the title drops its own.
        titleOverflowTooltip={tooltip === undefined}
      />
    </div>
  );
  // Always wrapped, and suppressed without a tooltip: adding or removing one
  // keeps the same root, so a focused badge keeps focus.
  return (
    <Tooltip
      tooltip={tooltip ?? title}
      suppressed={tooltip === undefined}
      side="top"
    >
      {badge}
    </Tooltip>
  );
}

export { Badge, type BadgeProps, type BadgeSize };
export { BADGE_COLORS, badgeTextClass } from "@opal/components/badge/colors";
