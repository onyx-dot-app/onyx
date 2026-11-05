"use client";

import "@opal/layouts/content/styles.css";
import { useEffect, useImperativeHandle, useRef, useState } from "react";
import {
  Badge,
  Button,
  OverflowText,
  Text,
  Tooltip,
  type BadgeProps,
  type TextColor,
  type TextFont,
} from "@opal/components";
import SvgAlertCircle from "@opal/icons/alert-circle";
import SvgAlertTriangle from "@opal/icons/alert-triangle";
import SvgEdit from "@opal/icons/edit";
import SvgXOctagon from "@opal/icons/x-octagon";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import { widthVariants } from "@opal/shared";
import { useOpalStrings } from "@opal/strings";
import type {
  ColorTypes,
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
type ContentBadge = BadgeProps & { tooltip?: string };

/** Starts a title edit from a control outside the content. */
interface ContentEditHandle {
  startEditing: () => void;
}

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

  /** Called with the new title when an edit is committed. */
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
   * Color mode for the icon + title pair.
   *
   * - `"default"` — `text-04` for both icon and title
   * - `"muted"` — `text-03` for both
   * - `"success"` / `"warning"` / `"danger"` — the status colour on the icon,
   *   `text-03` on the title: the icon carries the state
   * - `"interactive"` — inherits from the parent `.interactive` element's
   *   `--interactive-foreground` / `--interactive-foreground-icon` variables
   *
   * @default "default"
   */
  color?: ColorTypes;

  /**
   * Overrides the title's colour only; `color` still picks the icon and the
   * description. Inside an interactive surface the override holds at rest and
   * yields to hover, pressed, selected and disabled.
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

      /** A badge beside the title. */
      badge?: ContentBadge;

      orientation?: ContentOrientation;
    } & NoMoreIcons)
  | ({
      font: ContentHeadingFont;
      orientation: "stacked";
      /** A small connector icon after the icon, in `text-03`. */
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
  "heading-h1": 64,
  "heading-h2": 36,
  "heading-h3": 28,
  "heading-h3-muted": 28,
  "main-content-body": 24,
  "main-content-emphasis": 24,
  "main-content-muted": 24,
  "main-content-mono": 23,
  "main-ui-body": 20,
  "main-ui-muted": 20,
  "main-ui-action": 20,
  "main-ui-mono": 20,
  "secondary-body": 16,
  "secondary-action": 16,
  "secondary-mono": 16,
  "secondary-mono-label": 16,
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
 * The `titleColor` override, set inline on the colour wrapper. It rides an
 * unregistered variable that the colour modes read with the mode's tone as
 * fallback, so the disabled rule still wins.
 */
function titleColorStyle(
  titleColor: Exclude<TextColor, "inherit"> | undefined
): React.CSSProperties | undefined {
  // SAFETY: CSSProperties has no index for custom properties; the object
  // holds only the one custom property the stylesheet reads.
  return titleColor
    ? ({
        "--content-title-color": `var(--${titleColor})`,
      } as React.CSSProperties)
    : undefined;
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
 * 2px padding, so the glyph is the line height less 4px.
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
      {maxLines ? (
        <OverflowText
          font="secondary-body"
          color="inherit"
          as="p"
          maxLines={maxLines}
        >
          {description}
        </OverflowText>
      ) : (
        <Text font="secondary-body" color="inherit" as="p">
          {description}
        </Text>
      )}
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

  // An empty edit keeps the old title.
  function commit() {
    const value = editValue.trim();
    if (value && value !== toPlainString(title)) onTitleChange?.(value);
    setEditing(false);
  }

  const hasDescription = !!description && !!toPlainString(description);
  const hasIconRow = !!(icon || MoreIcon1 || moreIcon2);

  return (
    <div
      className={widthVariants[width]}
      data-content-color={color}
      style={titleColorStyle(titleColor)}
    >
      <div
        ref={ref}
        className="opal-content"
        data-opal-content
        data-orientation={orientation}
      >
        {hasIconRow && (
          <div className="opal-content-icon-row">
            {icon && (
              <ContentIcon icon={icon} font={font} enlarged={enlargedIcon} />
            )}
            {MoreIcon1 && (
              // The connector between two marks: smaller, and in the
              // secondary foreground rather than the icon colour.
              <div className="opal-content-more-icon">
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
            ) : titleMaxLines ? (
              <OverflowText
                // Lets a host (a toast) measure whether a clamped title overflows.
                data-opal-content-title=""
                font={font}
                color="inherit"
                maxLines={titleMaxLines}
                strikethrough={strikethrough}
                role={role}
                onClick={editable ? handleTitleClick : undefined}
              >
                {title}
              </OverflowText>
            ) : (
              <Text
                data-opal-content-title=""
                font={font}
                color="inherit"
                strikethrough={strikethrough}
                title={toPlainString(title)}
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

            {badge &&
              (() => {
                const { tooltip, ...badgeProps } = badge;
                return (
                  <span className="opal-content-badge">
                    <Tooltip tooltip={tooltip} side="top">
                      <Badge {...badgeProps} />
                    </Tooltip>
                  </span>
                );
              })()}

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
// Exports
// ---------------------------------------------------------------------------

export {
  Content,
  ContentDescription,
  ContentIcon,
  FONT_LINE_HEIGHT,
  titleColorStyle,
  type ContentProps,
  type ContentOrientation,
  type ContentExtrasFont,
  type ContentHeadingFont,
  type ContentAuxIcon,
  type ContentSuffix,
  type ContentBadge,
  type ContentEditHandle,
  type ContentDescriptionProps,
};
