"use client";

import "@opal/components/tag/styles.css";
import type {
  IconFunctionComponent,
  RichStr,
  WithoutStyles,
} from "@opal/types";
import { Text, Tooltip, type TextFont } from "@opal/components";
import { SvgAlertTriangle, SvgX } from "@opal/icons";
import { cn } from "@opal/utils";
import { TAG_COLORS, type TagColor } from "@opal/components/tag/colors";
import { useOpalStrings } from "@opal/strings";

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

interface TagBaseProps extends Omit<
  WithoutStyles<React.HTMLAttributes<HTMLElement>>,
  "title" | "color" | "children" | "onClick"
> {
  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /** Tag label text. */
  title: string | RichStr;

  /** Color variant. Default: `"gray"`. */
  color?: TagColor;

  /** Look of the passive tag. Default: `"default"`. */
  variant?: TagVariant;

  /** Icon color, when it differs from `color` (a gray pill with an orange icon). */
  iconColor?: TagColor;

  /** Size variant. Default: `"sm"`. */
  size?: TagSize;

  /** Optional typography override for the surrounding surface. */
  font?: TextFont;

  /**
   * Switches to the editable tag (Figma Tag `Type=Editable`): remove button,
   * gray hover, and the dark focus-within treatment chip fields use as the
   * keyboard-selection state before deleting a tag.
   */
  onRemove?: () => void;

  /**
   * Editable only: whether the remove button is a Tab stop. A chip field
   * walks its chips with the arrows and keeps Tab for leaving the field.
   * @default true
   */
  removeInTabOrder?: boolean;

  /** Editable only: dims the tag and hides the remove button. */
  disabled?: boolean;

  /** Secondary text rendered after the title in `text-03`. */
  value?: string | RichStr;

  /**
   * Cap the title width with an ellipsis (120px `sm`, 160px `md`).
   * Editable tags are always capped, per the Figma spec.
   */
  truncate?: boolean;

  /** Hover tooltip. Defaults to string titles on editable or truncated tags. */
  tooltip?: string;

  /** Warning indicator after the title. */
  error?: boolean;
}

/** Passive or editable tag: the root is a `div`. */
interface TagDivProps extends TagBaseProps {
  ref?: React.Ref<HTMLDivElement>;
  onClick?: never;
}

/**
 * Clickable tag: the root is a `button`. As a popover or dropdown trigger it
 * shows the inverted look while `data-state="open"` or `aria-expanded="true"`.
 * A clickable tag cannot be editable.
 */
interface TagButtonProps extends TagBaseProps {
  ref?: React.Ref<HTMLButtonElement>;
  onClick: React.MouseEventHandler<HTMLButtonElement>;
  onRemove?: never;
}

type TagProps = TagDivProps | TagButtonProps;

function isClickableTag(props: TagProps): props is TagButtonProps {
  return props.onClick !== undefined;
}

// ---------------------------------------------------------------------------
// Tag
// ---------------------------------------------------------------------------

// Class of the editable tag's remove control. Exported so composites (chip
// fields) can target it for keyboard flows without a fragile string copy.
const TAG_REMOVE_CLASS = "opal-auxiliary-tag-remove";

function Tag(props: TagProps) {
  const {
    ref: _ref,
    icon: Icon,
    title,
    color = "gray",
    variant = "default",
    iconColor,
    size = "sm",
    font: fontOverride,
    onRemove,
    removeInTabOrder = true,
    disabled = false,
    value,
    truncate = false,
    tooltip,
    error = false,
    onClick: _onClick,
    ...rest
  } = props;
  const strings = useOpalStrings();
  const config = TAG_COLORS[color];
  const editable = onRemove !== undefined;
  const capped = editable || truncate;

  const font =
    fontOverride ??
    (size === "sm"
      ? "figure-small-value"
      : editable
        ? "main-ui-body"
        : "secondary-body");

  const neutralLabel = variant !== "default" || (editable && color === "gray");
  // Editable gray reads in text-04 per the Figma spec. TAG_COLORS.gray
  // (text-03) stays for the passive metadata tag.
  const textClass = neutralLabel ? "text-text-04" : config.text;
  const iconClass = iconColor
    ? TAG_COLORS[iconColor].text
    : variant === "default"
      ? textClass
      : config.text;

  const className = cn(
    "opal-auxiliary-tag",
    variant !== "count" && config.bg,
    textClass
  );
  const dataAttrs = {
    "data-size": size,
    "data-type": editable ? "editable" : undefined,
    "data-variant": variant,
    "data-color": color,
    "data-disabled": (editable && disabled) || undefined,
  };

  const content = (
    <>
      {Icon && (
        <div className="opal-auxiliary-tag-icon-container">
          <Icon
            className={cn("opal-auxiliary-tag-icon", iconClass)}
            data-fixed-color={iconColor !== undefined || undefined}
          />
        </div>
      )}
      <span className="opal-auxiliary-tag-text">
        <span
          className={cn(
            "opal-auxiliary-tag-label",
            capped && "opal-auxiliary-tag-capped"
          )}
        >
          <Text font={font} color="inherit" wordWrap="whitespace-nowrap">
            {title}
          </Text>
        </span>
        {value !== undefined && (
          <span className="opal-auxiliary-tag-value">
            <Text font={font} color="inherit" wordWrap="whitespace-nowrap">
              {value}
            </Text>
          </span>
        )}
      </span>
      {error && <SvgAlertTriangle className="opal-auxiliary-tag-error-icon" />}
      {editable &&
        !disabled && (
          // raw-ok: the remove control is 16px (md) / 12px (sm), and Button's fixed sizes bottom out at 16px, so the tag owns its remove sizing
          <button
            type="button"
            className={TAG_REMOVE_CLASS}
            tabIndex={removeInTabOrder ? undefined : -1}
            aria-label={
              typeof title === "string"
                ? strings.removeItem(title)
                : strings.remove
            }
            onClick={(event) => {
              event.stopPropagation();
              onRemove();
            }}
          >
            <SvgX />
          </button>
        )}
    </>
  );

  const tag = isClickableTag(props) ? (
    // raw-ok: a tag-shaped trigger (Stack Trace, failed-entity pills) keeps the tag metrics, which no Button size matches
    <button
      ref={props.ref}
      type="button"
      {...rest}
      className={className}
      {...dataAttrs}
      data-clickable="true"
      onClick={props.onClick}
    >
      {content}
    </button>
  ) : (
    <div ref={props.ref} {...rest} className={className} {...dataAttrs}>
      {content}
    </div>
  );

  const tooltipText =
    tooltip ?? (capped && typeof title === "string" ? title : undefined);

  return (
    <Tooltip tooltip={tooltipText} side="top">
      {tag}
    </Tooltip>
  );
}

export { Tag, TAG_REMOVE_CLASS, type TagProps, type TagSize, type TagVariant };
export { TAG_COLORS, type TagColor } from "@opal/components/tag/colors";
