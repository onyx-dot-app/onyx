"use client";

import "@opal/components/buttons/select-button/styles.css";
import { Interactive, type InteractiveStatefulProps } from "@opal/core";
import type {
  ContainerSizeVariants,
  ExtremaSizeVariants,
  IconFunctionComponent,
  RichStr,
  Rounding,
} from "@opal/types";
import {
  Button,
  Text,
  Tooltip,
  type TextColor,
  type TextFont,
  type TooltipSide,
} from "@opal/components";
import { SvgX } from "@opal/icons";
import { cn } from "@opal/utils";
import { iconWrapper } from "@opal/components/buttons/icon-wrapper";
import { ChevronIcon } from "@opal/components/buttons/chevron";
import { resolveTriggerInteraction } from "@opal/components/buttons/trigger-interaction";
import { useOpalStrings } from "@opal/strings";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Content props — a discriminated union on `foldable` that enforces:
 *
 * - `foldable: boolean` → `icon` and `children` are required (icon stays
 *                          visible, label + trailing icon fold away when true)
 * - `foldable?: false`   → at least one of `icon` or `children` must be provided
 */
type SelectButtonContentProps =
  | {
      foldable: boolean;
      icon: IconFunctionComponent;
      children: string | RichStr;
    }
  | {
      foldable?: false;
      icon?: IconFunctionComponent;
      children: string | RichStr;
    }
  | {
      foldable?: false;
      icon: IconFunctionComponent;
      children?: string | RichStr;
    };

/**
 * The trailing slot holds one thing: a free `rightIcon`, or the dropdown
 * `chevron`. `onClear` needs the chevron, since the clear button takes its
 * place.
 */
type SelectButtonTrailingProps =
  | {
      /** Icon after the label. */
      rightIcon?: IconFunctionComponent;
      chevron?: false;
      onClear?: never;
    }
  | {
      rightIcon?: never;
      /**
       * A trailing chevron for a dropdown or popover trigger. It rotates while
       * the trigger is open.
       */
      chevron: true;
      /**
       * Filter triggers: while `state="selected"`, a clear (X) button replaces
       * the chevron and calls this.
       */
      onClear?: () => void;
    };

type SelectButtonProps = InteractiveStatefulProps &
  SelectButtonContentProps &
  SelectButtonTrailingProps & {
    /**
     * Size preset — controls gap, text size, and Container height/rounding.
     */
    size?: ContainerSizeVariants;

    /** Tooltip text shown on hover. */
    tooltip?: string;

    /** Width preset. `"fit"` shrink-wraps, `"full"` stretches to parent width. */
    width?: ExtremaSizeVariants;

    /**
     * Content justify mode. When `"between"`, icon + label group left and the
     * trailing icon pushes to the right edge. Default keeps all items in a
     * tight row.
     */
    justifyContent?: "between";

    /** Override the label font (defaults to the size-derived body font). */
    labelFont?: TextFont;

    /** Override the label color (defaults to the variant's interactive color). */
    labelColor?: TextColor;

    /** Override the default rounding derived from `size`. */
    rounding?: Rounding;

    /** Which side the tooltip appears on. */
    tooltipSide?: TooltipSide;

    /** Applies disabled styling and suppresses clicks. */
    disabled?: boolean;
  };

// ---------------------------------------------------------------------------
// SelectButton
// ---------------------------------------------------------------------------

function SelectButton({
  icon: Icon,
  children,
  rightIcon,
  chevron,
  onClear,
  size = "lg",
  type = "button",
  foldable,
  width,
  justifyContent,
  labelFont,
  labelColor,
  rounding: roundingOverride,
  tooltip,
  tooltipSide = "top",
  interaction,
  disabled,
  ...statefulProps
}: SelectButtonProps) {
  const strings = useOpalStrings();
  // Inside a Radix or Opal Dropdown trigger, the open state drives the hover
  // look (and the chevron's rotation) unless `interaction` is set.
  const resolvedInteraction = resolveTriggerInteraction(
    interaction,
    statefulProps
  );
  const isLarge = size === "lg";
  const showClear =
    chevron === true &&
    onClear !== undefined &&
    statefulProps.state === "selected";
  const TrailingIcon = chevron ? ChevronIcon : rightIcon;

  const labelEl = children ? (
    <Text
      font={labelFont ?? (isLarge ? "main-ui-body" : "secondary-body")}
      color={labelColor ?? "inherit"}
      wordWrap="whitespace-nowrap"
    >
      {children}
    </Text>
  ) : null;

  // The clear button overlays the chevron, which keeps its space so the
  // button's width does not change.
  const trailingEl = onClear ? (
    <div style={{ visibility: showClear ? "hidden" : "visible" }}>
      {iconWrapper(TrailingIcon, size, !!children)}
    </div>
  ) : (
    iconWrapper(TrailingIcon, size, !!children)
  );

  const isBetween = justifyContent === "between";

  const button = (
    <Interactive.Stateful
      disabled={disabled}
      interaction={resolvedInteraction}
      {...statefulProps}
    >
      <Interactive.Container
        type={type}
        size={size}
        width={width}
        rounding={roundingOverride ?? (isLarge ? 3 : size === "2xs" ? 1 : 2)}
      >
        <div
          className={cn(
            "opal-select-content",
            isBetween && "w-full justify-between",
            foldable && !isBetween && "interactive-foldable-host"
          )}
        >
          {isBetween ? (
            <>
              <span className="opal-select-content">
                {iconWrapper(Icon, size, !!children)}
                {labelEl}
              </span>
              {trailingEl}
            </>
          ) : foldable ? (
            <>
              {iconWrapper(Icon, size, false)}
              <Interactive.Foldable>
                {labelEl}
                {trailingEl}
              </Interactive.Foldable>
            </>
          ) : (
            <>
              {iconWrapper(Icon, size, !!children)}
              {labelEl}
              {trailingEl}
            </>
          )}
        </div>
      </Interactive.Container>
    </Interactive.Stateful>
  );

  const withClear = onClear ? (
    <div className="relative">
      {button}
      {showClear && (
        <div className="absolute end-2 top-1/2 -translate-y-1/2">
          {/* Force hover state so the X stays visually prominent against
              the inverted selected background — without this it renders
              dimmed and looks disabled. */}
          <Button
            icon={SvgX}
            size="2xs"
            prominence="tertiary"
            tooltip={strings.clearFilter}
            interaction="hover"
            onClick={(e) => {
              e.stopPropagation();
              onClear();
            }}
          />
        </div>
      )}
    </div>
  ) : (
    button
  );

  const resolvedTooltip =
    tooltip ?? (foldable && disabled && children ? children : undefined);

  return (
    <Tooltip tooltip={resolvedTooltip} side={tooltipSide}>
      {withClear}
    </Tooltip>
  );
}

export { SelectButton, type SelectButtonProps };
