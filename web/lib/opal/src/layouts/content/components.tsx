"use client";

import "@opal/layouts/content/styles.css";
import { useEffect, useImperativeHandle, useRef, useState } from "react";
import {
  Badge,
  Button,
  Text,
  type BadgeProps,
  type TextColor,
  type TextFont,
} from "@opal/components";
import SvgAlertCircle from "@opal/icons/alert-circle";
import SvgAlertTriangle from "@opal/icons/alert-triangle";
import SvgEdit from "@opal/icons/edit";
import SvgXOctagon from "@opal/icons/x-octagon";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import { CONTENT_STATUS_COLORS } from "@opal/layouts/content/colors";
import { widthVariants } from "@opal/shared";
import { useOpalStrings } from "@opal/strings";
import type {
  StatusColor,
  ContainerSizeVariants,
  ExtremaSizeVariants,
  IconFunctionComponent,
  RichStr,
} from "@opal/types";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Where the icon sits: before the title (`"inline"`) or above it
 * (`"stacked"`). For an icon after the title, use `ReverseContent`.
 */
type ContentOrientation = "inline" | "stacked";

type ContentAuxIcon = "info-gray" | "info-blue" | "warning" | "error";

type ContentSuffix = "optional" | (string & {});

/** A badge beside the title, with an optional hover tooltip. */
type ContentBadge = BadgeProps;

/** One badge, or several in order, beside the title. */
type ContentBadges = ContentBadge | ContentBadge[];

/** Starts a title edit from a control outside the content. */
interface ContentEditHandle {
  startEditing: () => void;
}

/** A status colour, or `"interactive"` to follow the surrounding surface. */
type ContentColor = StatusColor | "interactive";

/** The title fonts that take a suffix, aux icon or badge beside the title. */
type ContentExtrasFont = Extract<
  TextFont,
  `main-ui-${string}` | `main-content-${string}` | `secondary-${string}`
>;

interface ContentBaseProps {
  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /**
   * Drop the icon box's 2px padding, so the icon is as tall as the title
   * line rather than 4px shorter. The box keeps its size, so nothing else
   * moves. Covers `icon` and `moreIcon2`.
   */
  enlargedIcon?: boolean;

  /** Main title text. */
  title: string | RichStr;

  /** Optional description below the title (`secondary-body`, `text-03`). */
  description?: string | RichStr;

  /**
   * Clamp the title to N lines; a cut title shows in full in a tooltip.
   * Omit to wrap freely.
   */
  titleMaxLines?: number;

  /**
   * A tooltip on every hover of the title. It replaces the full-title tooltip
   * of `titleMaxLines`, so a cut title shows only this.
   */
  titleTooltip?: string | RichStr;

  /**
   * With `titleMaxLines`: show a cut title in full in a tooltip. Turn it off
   * when a host puts its own tooltip around the content. Default: `true`.
   */
  titleOverflowTooltip?: boolean;

  /** Clamp the description to N lines; a cut one shows in a tooltip. */
  descriptionMaxLines?: number;

  /** Strike the title through, for an option that is switched off. */
  strikethrough?: boolean;

  /** ARIA role on the title element. */
  role?: string;

  /** Enable inline editing of the title. */
  editable?: boolean;

  /** Starts a title edit from an outside control; hides the built-in pencil. */
  editHandle?: React.Ref<ContentEditHandle>;

  /**
   * Called with the new, trimmed title when an edit is committed. An empty
   * title is passed on: the caller decides whether it resets or is ignored.
   */
  onTitleChange?: (newTitle: string) => void;

  /**
   * Tooltip and accessible name of the edit button. Pass translated text;
   * unset, it is the generic "Edit".
   */
  editTooltip?: string;

  /** When the pencil shows: on hover of the content, or at rest too. */
  editButton?: "hover" | "rest";

  /** Width preset. Default: `"full"`. */
  width?: ExtremaSizeVariants;

  /**
   * The content's colour. A status (`CONTENT_STATUS_COLORS`) tints the title
   * and the icon; `"default"` is the neutral `text-04`, and its icon follows
   * `titleColor`. `"interactive"` follows the surrounding interactive
   * surface, so its hover, selected and disabled colours reach the content.
   *
   * @default "default"
   */
  color?: ContentColor;

  /**
   * Overrides the title's colour only; the icon keeps `color`'s (except on
   * `"default"`, where it follows). Inside an interactive surface the
   * override holds at rest and yields to hover, pressed, selected and
   * disabled.
   */
  titleColor?: Exclude<TextColor, "inherit">;

  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;
}

/** Title fonts whose stacked layout takes `moreIcon1` / `moreIcon2`. */
type ContentHeadingFont = Extract<TextFont, `heading-${string}`>;

/** No extras beside the title. */
type NoExtras = { suffix?: never; auxIcon?: never; badge?: never };

/** No icon-row extras. */
type NoMoreIcons = { moreIcon1?: never; moreIcon2?: never };

/**
 * The title font decides which extras a `Content` takes:
 *
 * - `main-ui-*`, `main-content-*`, `secondary-*`: `suffix`, `auxIcon` and
 *   `badge` beside the title.
 * - `heading-*`: `moreIcon1` / `moreIcon2` in the icon row, when stacked.
 * - `figure-*`: neither, and no description (smaller than `secondary`).
 */
type ContentFontProps =
  | ({
      /**
       * The title's font. Every size derives from it: the icon container is
       * one title line tall, so the icon is that line height less 4px.
       * Default: `"main-ui-action"`.
       */
      font?: ContentExtrasFont;

      /**
       * Muted text beside the title, in the title's size and lighter weight.
       * `"optional"` is the translated "(Optional)".
       */
      suffix?: ContentSuffix;

      /** A status icon beside the title. */
      auxIcon?: ContentAuxIcon;

      /** One badge, or a list of badges, beside the title. */
      badge?: ContentBadges;

      orientation?: ContentOrientation;
    } & NoMoreIcons)
  | ({
      font: ContentHeadingFont;
      orientation: "stacked";
      /** A connector icon after the icon, in `text-03`: its box is 12px smaller than the icon box. */
      moreIcon1?: IconFunctionComponent;
      /** A peer of the icon, the same size, after `moreIcon1`. */
      moreIcon2?: IconFunctionComponent;
    } & NoExtras)
  | ({
      font: ContentHeadingFont;
      orientation?: "inline";
    } & NoExtras &
      NoMoreIcons)
  | ({
      /** Figure titles are smaller than `secondary`: no description. */
      font: Extract<TextFont, `figure-${string}`>;
      orientation?: ContentOrientation;
      description?: never;
      descriptionMaxLines?: never;
    } & NoExtras &
      NoMoreIcons);

type ContentProps = ContentBaseProps & ContentFontProps;

// ---------------------------------------------------------------------------
// Font metrics
// ---------------------------------------------------------------------------

/** Each font's line height in px, from the typography presets. */
const FONT_LINE_HEIGHT: Record<TextFont, number> = {
  "heading-hero": 48,
  "heading-headline": 36,
  "heading-section": 28,
  "heading-section-muted": 28,
  "main-content-body": 24,
  "main-content-emphasis": 24,
  "main-content-muted": 24,
  "main-content-mono": 24,
  "main-ui-body": 20,
  "main-ui-muted": 20,
  "main-ui-action": 20,
  "main-ui-mono": 20,
  "secondary-body": 16,
  "secondary-action": 16,
  "secondary-mono": 16,
  "figure-small-label": 12,
  "figure-small-value": 12,
  "figure-keystroke": 16,
};

/** The largest button that fits on one title line. */
function editButtonSize(lineHeight: number): ContainerSizeVariants {
  if (lineHeight >= 36) return "lg";
  if (lineHeight >= 28) return "md";
  if (lineHeight >= 24) return "sm";
  if (lineHeight >= 20) return "xs";
  return "2xs";
}

/**
 * The suffix: the title's size in its lightest weight. Only the `main-ui-*`,
 * `main-content-*` and `secondary-*` titles take one.
 */
function suffixFont(font: TextFont): TextFont {
  if (font.startsWith("main-ui")) return "main-ui-muted";
  if (font.startsWith("main-content")) return "main-content-muted";
  return "secondary-body";
}

/**
 * Whether the icon sits 0.25rem from the text. `secondary-*` and `figure-*`
 * titles put the icon flush against it.
 */
function hasIconGap(font: TextFont): boolean {
  return !font.startsWith("secondary-") && !font.startsWith("figure-");
}

/**
 * The colour variables, set inline on the colour wrapper: the status colour,
 * and the `titleColor` override. The override rides an unregistered variable
 * that the colour modes read with the status colour as fallback, so the
 * disabled rule still wins.
 */
function contentColorStyle(
  color: ContentColor,
  titleColor: Exclude<TextColor, "inherit"> | undefined
): React.CSSProperties {
  // SAFETY: CSSProperties has no index for custom properties; the object
  // holds only the two custom properties the stylesheet reads.
  return {
    ...(color !== "interactive" && {
      "--content-status-color": CONTENT_STATUS_COLORS[color].fg,
    }),
    ...(titleColor && { "--content-title-color": `var(--${titleColor})` }),
  } as React.CSSProperties;
}

const AUX_ICON_CONFIG: Record<
  ContentAuxIcon,
  { icon: IconFunctionComponent; colorClass: string }
> = {
  "info-gray": { icon: SvgAlertCircle, colorClass: "text-text-02" },
  "info-blue": { icon: SvgAlertCircle, colorClass: "text-status-info-05" },
  warning: { icon: SvgAlertTriangle, colorClass: "text-status-warning-05" },
  error: { icon: SvgXOctagon, colorClass: "text-status-error-05" },
};

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

/**
 * An icon in a square one title line tall (`1lh` of the title font), with
 * 2px padding (1px for `figure-*`).
 */
function ContentIcon({
  icon: Icon,
  font,
  enlarged = false,
  className,
}: {
  icon: IconFunctionComponent;
  font: TextFont;
  /** No padding: the glyph is the full line height. */
  enlarged?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn("opal-content-icon", `font-${font}`, className)}
      data-enlarged={enlarged || undefined}
      data-figure={font.startsWith("figure-") || undefined}
    >
      <Icon className="opal-content-icon-glyph" />
    </div>
  );
}

interface ContentDescriptionProps {
  description: string | RichStr;
  maxLines?: number;
}

/** The description: `secondary-body` in the secondary foreground. */
function ContentDescription({
  description,
  maxLines,
}: ContentDescriptionProps) {
  return (
    <div className="opal-content-description">
      {/* Clamped, the full description shows in a tooltip when it is cut. */}
      <Text
        font="secondary-body"
        color="inherit"
        as="p"
        maxLines={maxLines}
        overflowTooltip={maxLines !== undefined}
      >
        {description}
      </Text>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Content
// ---------------------------------------------------------------------------

/**
 * An icon beside (or above) a title and an optional description. The title
 * `font` sets every size; `orientation` places the icon.
 */
function Content({
  font = "main-ui-action",
  orientation = "inline",
  icon,
  enlargedIcon = false,
  title,
  description,
  titleMaxLines,
  titleTooltip,
  titleOverflowTooltip = true,
  descriptionMaxLines,
  strikethrough,
  suffix,
  auxIcon,
  badge,
  role,
  editable,
  editHandle,
  onTitleChange,
  editTooltip,
  editButton = "hover",
  width = "full",
  color = "default",
  titleColor,
  moreIcon1: MoreIcon1,
  moreIcon2,
  ref,
}: ContentProps) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(toPlainString(title));
  const strings = useOpalStrings();
  const inputRef = useRef<HTMLInputElement>(null);
  const lineHeight = FONT_LINE_HEIGHT[font];

  // Move focus to the edit input as soon as editing starts.
  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  function startEditing() {
    setEditValue(toPlainString(title));
    setEditing(true);
  }
  useImperativeHandle(editHandle, () => ({ startEditing }), [title]);

  // Starting or making an edit must not double as a click on a parent row.
  function handleTitleClick(e: React.MouseEvent) {
    e.stopPropagation();
    startEditing();
  }

  function commit() {
    const value = editValue.trim();
    if (value !== toPlainString(title)) onTitleChange?.(value);
    setEditing(false);
  }

  const hasDescription = !!description && !!toPlainString(description);
  const badges = badge === undefined ? [] : [badge].flat();
  const hasIconRow = !!(icon || MoreIcon1 || moreIcon2);

  return (
    <div
      className={widthVariants[width]}
      data-content-color={color}
      style={contentColorStyle(color, titleColor)}
    >
      <div
        ref={ref}
        className="opal-content"
        data-opal-content
        data-orientation={orientation}
        data-flush={!hasIconGap(font) || undefined}
      >
        {hasIconRow && (
          <div className="opal-content-icon-row">
            {icon && (
              <ContentIcon icon={icon} font={font} enlarged={enlargedIcon} />
            )}
            {MoreIcon1 && (
              // The connector between two marks: 12px smaller than the icon
              // box (the title font gives its `1lh`), in the secondary
              // foreground rather than the icon colour.
              <div className={cn("opal-content-more-icon", `font-${font}`)}>
                <MoreIcon1 className="opal-content-icon-glyph" />
              </div>
            )}
            {moreIcon2 && (
              <ContentIcon
                icon={moreIcon2}
                font={font}
                enlarged={enlargedIcon}
              />
            )}
          </div>
        )}

        <div className="opal-content-text">
          <div className="opal-content-title-row">
            {editing ? (
              <div className="opal-content-input-sizer">
                <span
                  className={cn("opal-content-input-mirror", `font-${font}`)}
                >
                  {editValue || " "}
                </span>
                <input
                  ref={inputRef}
                  className={cn(
                    "opal-content-input",
                    `font-${font}`,
                    "text-text-04"
                  )}
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  onClick={(e) => e.stopPropagation()}
                  size={1}
                  onFocus={(e) => e.currentTarget.select()}
                  onBlur={commit}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commit();
                    if (e.key === "Escape") {
                      setEditValue(toPlainString(title));
                      setEditing(false);
                    }
                  }}
                />
              </div>
            ) : (
              <Text
                // Lets a host (a toast) measure whether a clamped title overflows.
                data-opal-content-title=""
                font={font}
                color="inherit"
                maxLines={titleMaxLines}
                // Clamped, a cut title shows in full in a tooltip.
                overflowTooltip={
                  titleMaxLines !== undefined && titleOverflowTooltip
                }
                tooltip={titleTooltip}
                strikethrough={strikethrough}
                // Unclamped and without a tooltip, the native title shows it.
                title={
                  titleMaxLines === undefined && titleTooltip === undefined
                    ? toPlainString(title)
                    : undefined
                }
                role={role}
                onClick={editable ? handleTitleClick : undefined}
              >
                {title}
              </Text>
            )}

            {suffix && (
              <div className="opal-content-suffix">
                <Text as="p" font={suffixFont(font)} color="inherit">
                  {suffix === "optional" ? strings.contentOptional : suffix}
                </Text>
              </div>
            )}

            {auxIcon &&
              (() => {
                const { icon: AuxIcon, colorClass } = AUX_ICON_CONFIG[auxIcon];
                return (
                  <div className="opal-content-aux-icon">
                    <AuxIcon
                      className={cn("opal-content-aux-glyph", colorClass)}
                    />
                  </div>
                );
              })()}

            {badges.length > 0 && (
              <span className="opal-content-badge">
                {badges.map((b, i) => (
                  <Badge key={i} {...b} />
                ))}
              </span>
            )}

            {editable && !editing && editHandle == null && (
              <div className="opal-content-edit-button" data-show={editButton}>
                <Button
                  icon={SvgEdit}
                  prominence="internal"
                  size={editButtonSize(lineHeight)}
                  aria-label={editTooltip || strings.edit}
                  tooltip={editTooltip || strings.edit}
                  tooltipSide="end"
                  onClick={handleTitleClick}
                />
              </div>
            )}
          </div>

          {hasDescription && (
            <ContentDescription
              description={description}
              maxLines={descriptionMaxLines}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ContentIndent
// ---------------------------------------------------------------------------

interface ContentIndentProps {
  /** The title font of the `Content` above, which sets its icon box. */
  font: TextFont;
  children: React.ReactNode;
}

/**
 * Lines its children up under a `Content`'s title and description: indented
 * by one icon box (the title's line height) and the icon gap. Use it for
 * rows that continue a `Content` with an icon, such as a link or a detail line.
 */
function ContentIndent({ font, children }: ContentIndentProps) {
  const gap = hasIconGap(font) ? 4 : 0;
  return (
    <div
      style={{
        paddingInlineStart: `${(FONT_LINE_HEIGHT[font] + gap) / 16}rem`,
      }}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export {
  Content,
  ContentDescription,
  ContentIndent,
  type ContentIndentProps,
  ContentIcon,
  FONT_LINE_HEIGHT,
  contentColorStyle,
  hasIconGap,
  type ContentColor,
  type ContentProps,
  type ContentOrientation,
  type ContentExtrasFont,
  type ContentHeadingFont,
  type ContentAuxIcon,
  type ContentSuffix,
  type ContentBadge,
  type ContentBadges,
  type ContentEditHandle,
  type ContentDescriptionProps,
};
