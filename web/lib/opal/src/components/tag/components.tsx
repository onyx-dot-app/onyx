"use client";

import "@opal/components/tag/styles.css";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { TAG_COLORS, type TagColor } from "@opal/components/tag/colors";
import { Content } from "@opal/layouts";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TagSize = "sm" | "md";

/**
 * - `"default"`: tinted background, icon and label in the color's text.
 * - `"status"`: tinted background, icon in the color's text, `text-04` label.
 * - `"count"`: no background, icon in the color's text, `text-04` label.
 */
type TagVariant = "default" | "status" | "count";

// Takes no DOM attributes. The ref and anything a wrapping Tooltip or
// popover trigger injects at runtime still reach the root, so either can
// wrap a Tag.
type TagProps = {
  ref?: React.Ref<HTMLDivElement>;

  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /** Tag label text. */
  title: string | RichStr;

  /** Color variant. Default: `"gray"`. */
  color?: TagColor;

  /** How the color is applied. Default: `"default"`. */
  variant?: TagVariant;

  /** Size variant. Default: `"sm"`. */
  size?: TagSize;
};

// ---------------------------------------------------------------------------
// Tag
// ---------------------------------------------------------------------------

/**
 * A small coloured label: an icon and a title in a tinted pill. It does
 * nothing on click. For a removable, clickable or field chip, use `Chip`.
 */
function Tag({
  icon,
  title,
  color = "gray",
  variant = "default",
  size = "sm",
  ...rest
}: TagProps) {
  const config = TAG_COLORS[color];

  // SAFETY: CSSProperties has no index for custom properties; the object
  // holds only the one custom property the stylesheet reads.
  const iconColorStyle = {
    "--opal-tag-icon-color": config.fg,
  } as React.CSSProperties;

  return (
    <div
      {...rest}
      className={cn(
        "opal-auxiliary-tag",
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

export { Tag, type TagProps, type TagSize, type TagVariant };
export { TAG_COLORS, type TagColor } from "@opal/components/tag/colors";
