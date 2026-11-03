"use client";

import "@opal/components/chip/styles.css";
import type {
  IconFunctionComponent,
  RichStr,
  WithoutStyles,
} from "@opal/types";
import { Button, Tooltip } from "@opal/components";
import { resolveTriggerInteraction } from "@opal/components/buttons/trigger-interaction";
import { TAG_COLORS, type TagColor } from "@opal/components/tag/colors";
import { Disabled, Interactive } from "@opal/core";
import { SvgX } from "@opal/icons";
import { Content } from "@opal/layouts";
import { useOpalStrings } from "@opal/strings";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ChipBaseProps = Omit<
  WithoutStyles<React.HTMLAttributes<HTMLElement>>,
  "title" | "color" | "children" | "onClick"
> & {
  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /** Icon colour, when it is not the chip's gray (an orange warning icon). */
  iconColor?: TagColor;

  /** Chip label text. */
  title: string | RichStr;

  /** Cap the title at 160px with an ellipsis; a cut title shows on hover. */
  truncate?: boolean;

  /** Hover tooltip; on a disabled chip it explains why. */
  tooltip?: string;

  /** Warning icon after the title, for a value the field rejects. */
  error?: boolean;
};

/**
 * Static chip: no click, no remove. Looks like the others, without the hover;
 * a chip field's locked chip.
 */
type ChipStaticProps = ChipBaseProps & {
  ref?: React.Ref<HTMLDivElement>;
  /** Dims the whole chip. */
  disabled?: boolean;
  onClick?: never;
  onRemove?: never;
  removeInTabOrder?: never;
};

/** Removable chip: a remove Button after the title. */
type ChipRemovableProps = ChipBaseProps & {
  ref?: React.Ref<HTMLDivElement>;
  /** Unset, the chip is a static one. */
  onRemove?: () => void;
  /**
   * Whether the remove button is a Tab stop. A chip field walks its chips
   * with the arrows and keeps Tab for leaving the field.
   * @default true
   */
  removeInTabOrder?: boolean;
  /** Dims the whole chip and hides the remove button. */
  disabled?: boolean;
  onClick?: never;
};

/**
 * Clickable chip: a button. As a popover or dropdown trigger it shows the
 * hover look while open, as `Button` does; with `aria-pressed` it is a filter
 * toggle, inverted while pressed.
 */
type ChipButtonProps = ChipBaseProps & {
  ref?: React.Ref<HTMLButtonElement>;
  onClick: React.MouseEventHandler<HTMLButtonElement>;
  /** A trigger stays operable. */
  disabled?: never;
  onRemove?: never;
  removeInTabOrder?: never;
};

type ChipProps = ChipStaticProps | ChipRemovableProps | ChipButtonProps;

function isClickableChip(props: ChipProps): props is ChipButtonProps {
  return props.onClick !== undefined;
}

// ---------------------------------------------------------------------------
// Chip
// ---------------------------------------------------------------------------

// Attribute on the remove button. Exported so composites (chip fields) can
// target it for keyboard flows without a fragile string copy.
const CHIP_REMOVE_ATTR = "data-opal-chip-remove";

/**
 * A gray, md, `Interactive` pill: a chip-field value, a filter toggle or a
 * popover trigger. For a coloured label, use `Tag`.
 */
function Chip(props: ChipProps) {
  const {
    ref: _ref,
    icon,
    iconColor,
    title,
    truncate = false,
    tooltip,
    error = false,
    disabled = false,
    onClick: _onClick,
    onRemove,
    removeInTabOrder: _removeInTabOrder,
    ...rest
  } = props;
  const strings = useOpalStrings();
  const removable = onRemove !== undefined;

  const dataAttrs = {
    "data-removable": removable || undefined,
    "data-capped": removable || truncate || undefined,
    "data-fixed-color": iconColor !== undefined || undefined,
  };
  // SAFETY: CSSProperties has no index for custom properties; the object
  // holds only the one custom property the stylesheet reads.
  const iconColorStyle =
    iconColor !== undefined
      ? ({
          "--opal-chip-icon-color": TAG_COLORS[iconColor].fg,
        } as React.CSSProperties)
      : undefined;

  const content = (
    <>
      <Content
        sizePreset="secondary"
        variant="section"
        width="fit"
        color="interactive"
        icon={icon}
        title={title}
        titleMaxLines={1}
        auxIcon={error ? "warning" : undefined}
      />
      {removable && !disabled && (
        <Button
          // The literal of CHIP_REMOVE_ATTR: JSX takes no computed names.
          data-opal-chip-remove=""
          icon={SvgX}
          prominence="internal"
          size="2xs"
          tabIndex={props.removeInTabOrder === false ? -1 : undefined}
          aria-label={
            typeof title === "string"
              ? strings.removeItem(title)
              : strings.remove
          }
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
        />
      )}
    </>
  );

  let chip: React.ReactNode;
  if (isClickableChip(props)) {
    // A popup trigger takes the hover look while open, as Button does.
    const popup = rest["aria-haspopup"];
    const isPopupTrigger =
      popup !== undefined && popup !== false && popup !== "false";
    const interaction = isPopupTrigger
      ? resolveTriggerInteraction(undefined, rest)
      : "rest";
    const pressed = rest["aria-pressed"];
    const button = (
      <button
        ref={props.ref}
        type="button"
        {...rest}
        className="opal-chip"
        style={iconColorStyle}
        {...dataAttrs}
      >
        {content}
      </button>
    );
    // A toggle (aria-pressed) is a filter chip: it shows its pressed state.
    chip =
      pressed !== undefined ? (
        <Interactive.Stateful
          variant="select-filter"
          state={pressed === true || pressed === "true" ? "selected" : "empty"}
          interaction={interaction}
          type="button"
          onClick={props.onClick}
        >
          {button}
        </Interactive.Stateful>
      ) : (
        <Interactive.Stateless
          variant="default"
          prominence="secondary"
          interaction={interaction}
          type="button"
          onClick={props.onClick}
        >
          {button}
        </Interactive.Stateless>
      );
  } else {
    chip = (
      <Interactive.Stateless
        variant="default"
        prominence="secondary"
        // A static chip keeps the look without the hover.
        passive={!removable}
      >
        <div
          ref={props.ref}
          {...rest}
          className="opal-chip"
          style={iconColorStyle}
          {...dataAttrs}
        >
          {content}
        </div>
      </Interactive.Stateless>
    );
  }

  // A disabled chip dims as a whole; its tooltip says why.
  if (disabled) {
    return (
      <Disabled disabled tooltip={tooltip} tooltipSide="top">
        {chip}
      </Disabled>
    );
  }
  return (
    <Tooltip tooltip={tooltip} side="top">
      {chip}
    </Tooltip>
  );
}

export { Chip, CHIP_REMOVE_ATTR, type ChipProps };
