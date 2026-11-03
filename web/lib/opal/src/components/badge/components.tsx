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
import { Tooltip } from "@opal/components/tooltip/components";
import { Interactive } from "@opal/core";
import { Content } from "@opal/layouts";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Height on the Tailwind scale: `4` is 1rem, `5` is 1.25rem, `6` is 1.5rem. */
type BadgeSize = 4 | 5 | 6;

// Takes no DOM attributes. The ref and anything a wrapping Tooltip or
// popover trigger injects at runtime still reach the root, so either can
// wrap a static Badge.
type BadgeBaseProps = {
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

type BadgeProps = BadgeBaseProps & {
  onClick?: never;
  tooltip?: never;
  "aria-pressed"?: never;
};

/** A badge that acts on click, such as a filter pill or a count that opens its details. */
type BadgeButtonProps = BadgeBaseProps & {
  onClick: () => void;
  /** The hover tooltip and the button's name, since the title may be only a count. */
  tooltip: string;
  /** Set for a filter toggle, which shows selected while pressed. */
  "aria-pressed"?: boolean;
};

// ---------------------------------------------------------------------------
// Badge
// ---------------------------------------------------------------------------

/**
 * A small coloured label: an icon and a title in a tinted pill. With
 * `onClick` it is a button, or with `aria-pressed` a filter toggle. For a
 * gray, removable or field pill, use `Tag`.
 */
function Badge({
  ref,
  icon,
  title,
  color = "default",
  textColor = "inherit",
  size = 4,
  onClick,
  tooltip,
  "aria-pressed": pressed,
  ...rest
}: BadgeProps | BadgeButtonProps) {
  const config = BADGE_COLORS[color];

  // SAFETY: CSSProperties has no index for custom properties; the object
  // holds only the one custom property the stylesheet reads.
  const iconColorStyle = {
    "--opal-badge-icon-color": config.fg,
  } as React.CSSProperties;

  const badge = (
    <div
      ref={ref}
      {...(onClick === undefined ? rest : undefined)}
      className={cn(
        "opal-badge",
        config.bg,
        textColor === "inherit" ? config.text : TEXT_COLOR_CLASSES[textColor]
      )}
      style={iconColorStyle}
      data-size={size}
      data-pressed={pressed || undefined}
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
  if (onClick === undefined) return badge;

  // The focus ring follows the pill's corners.
  const container = (
    <Interactive.Container
      type="button"
      size="fit"
      rounding={size === 6 ? 2 : 1}
    >
      {badge}
    </Interactive.Container>
  );
  return (
    <Tooltip tooltip={tooltip} side="top">
      {pressed === undefined ? (
        <Interactive.Stateless
          {...rest}
          prominence="tertiary"
          aria-label={tooltip}
          onClick={onClick}
        >
          {container}
        </Interactive.Stateless>
      ) : (
        <Interactive.Stateful
          {...rest}
          variant="select-light"
          state={pressed ? "selected" : "empty"}
          aria-label={tooltip}
          aria-pressed={pressed}
          onClick={onClick}
        >
          {container}
        </Interactive.Stateful>
      )}
    </Tooltip>
  );
}

export { Badge, type BadgeButtonProps, type BadgeProps, type BadgeSize };
export { BADGE_COLORS } from "@opal/components/badge/colors";
