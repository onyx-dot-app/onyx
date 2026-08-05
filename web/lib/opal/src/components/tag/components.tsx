import "@opal/components/tag/styles.css";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { Text, Tooltip } from "@opal/components";
import { SvgAlertTriangle, SvgX } from "@opal/icons";
import { cn } from "@opal/utils";
import { TAG_COLORS, type TagColor } from "@opal/components/tag/colors";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TagSize = "sm" | "md";

interface TagProps {
  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /** Tag label text. */
  title: string | RichStr;

  /** Color variant. Default: `"gray"`. */
  color?: TagColor;

  /** Size variant. Default: `"sm"`. */
  size?: TagSize;

  /**
   * Switches to the editable tag (Figma Tag `Type=Editable`): remove button,
   * gray hover, and the dark focus-within treatment chip fields use as the
   * keyboard-selection state before deleting a tag.
   */
  onRemove?: () => void;

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

// ---------------------------------------------------------------------------
// Tag
// ---------------------------------------------------------------------------

// Class of the editable tag's remove control. Exported so composites (chip
// fields) can target it for keyboard flows without a fragile string copy.
const TAG_REMOVE_CLASS = "opal-auxiliary-tag-remove";

function Tag({
  icon: Icon,
  title,
  color = "gray",
  size = "sm",
  onRemove,
  disabled = false,
  value,
  truncate = false,
  tooltip,
  error = false,
}: TagProps) {
  const config = TAG_COLORS[color];
  const editable = onRemove !== undefined;
  const capped = editable || truncate;

  const font =
    size === "sm"
      ? "figure-small-value"
      : editable
        ? "main-ui-body"
        : "secondary-body";

  // Editable gray reads in text-04 per the Figma spec. TAG_COLORS.gray
  // (text-03) stays for the passive metadata tag.
  const textClass = editable && color === "gray" ? "text-text-04" : config.text;

  const tag = (
    <div
      className={cn("opal-auxiliary-tag", config.bg, textClass)}
      data-size={size}
      data-type={editable ? "editable" : undefined}
      data-color={color}
      data-disabled={(editable && disabled) || undefined}
    >
      {Icon && (
        <div className="opal-auxiliary-tag-icon-container">
          <Icon className={cn("opal-auxiliary-tag-icon", textClass)} />
        </div>
      )}
      <span className="opal-auxiliary-tag-text">
        <span
          className={cn(
            "opal-auxiliary-tag-label",
            capped && "opal-auxiliary-tag-capped"
          )}
        >
          <Text font={font} color="inherit" nowrap>
            {title}
          </Text>
        </span>
        {value !== undefined && (
          <span className="opal-auxiliary-tag-value">
            <Text font={font} color="inherit" nowrap>
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
            aria-label={
              typeof title === "string" ? `Remove ${title}` : "Remove"
            }
            onClick={(event) => {
              event.stopPropagation();
              onRemove();
            }}
          >
            <SvgX />
          </button>
        )}
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

export { Tag, TAG_REMOVE_CLASS, type TagProps, type TagSize };
export { TAG_COLORS, type TagColor } from "@opal/components/tag/colors";
