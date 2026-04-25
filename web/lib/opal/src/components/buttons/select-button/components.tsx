"use client";

import "@opal/components/buttons/select-button/styles.css";
import { Interactive, type InteractiveStatefulProps } from "@opal/core";
import type {
  ContainerSizeVariants,
  ExtremaSizeVariants,
  IconFunctionComponent,
  RichStr,
} from "@opal/types";
import { Text, Tooltip, type TooltipSide } from "@opal/components";
import { cn } from "@opal/utils";
import { iconWrapper } from "@opal/components/buttons/icon-wrapper";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Content props — a discriminated union on `foldable` that enforces:
 *
 * - `foldable: true`  → `icon` and `children` are required (icon stays visible,
 *                        label + rightIcon fold away)
 * - `foldable?: false` → at least one of `icon` or `children` must be provided
 */
type SelectButtonContentProps =
  | {
      foldable: true;
      icon: IconFunctionComponent;
      children: string | RichStr;
      rightIcon?: IconFunctionComponent;
    }
  | {
      foldable?: false;
      icon?: IconFunctionComponent;
      children: string | RichStr;
      rightIcon?: IconFunctionComponent;
    }
  | {
      foldable?: false;
      icon: IconFunctionComponent;
      children?: string | RichStr;
      rightIcon?: IconFunctionComponent;
    };

type SelectButtonProps = InteractiveStatefulProps &
  SelectButtonContentProps & {
    /**
     * Size preset — controls gap, text size, and Container height/rounding.
     */
    size?: ContainerSizeVariants;

    /** Tooltip text shown on hover. */
    tooltip?: string;

    /** Width preset. `"fit"` shrink-wraps, `"full"` stretches to parent width. */
    width?: ExtremaSizeVariants;

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
  rightIcon: RightIcon,
  size = "lg",
  type = "button",
  foldable,
  width,
  tooltip,
  tooltipSide = "top",
  disabled,
  ...statefulProps
}: SelectButtonProps) {
  const isLarge = size === "lg";

  const labelEl = children ? (
    <Text
      font={isLarge ? "main-ui-body" : "secondary-body"}
      color="inherit"
      nowrap
    >
      {children}
    </Text>
  ) : null;

  const button = (
    <Interactive.Stateful disabled={disabled} {...statefulProps}>
      <Interactive.Container
        type={type}
        size={size}
        width={width}
        rounding={isLarge ? "md" : size === "2xs" ? "xs" : "sm"}
      >
        <div
          className={cn(
            "opal-select-button",
            foldable && "interactive-foldable-host"
          )}
        >
          {iconWrapper(Icon, size, !foldable && !!children)}

          {foldable ? (
            <Interactive.Foldable>
              {labelEl}
              {iconWrapper(RightIcon, size, !!children)}
            </Interactive.Foldable>
          ) : (
            <>
              {labelEl}
              {iconWrapper(RightIcon, size, !!children)}
            </>
          )}
        </div>
      </Interactive.Container>
    </Interactive.Stateful>
  );

  const resolvedTooltip =
    tooltip ?? (foldable && disabled && children ? children : undefined);

  return (
    <Tooltip tooltip={resolvedTooltip} side={tooltipSide}>
      {button}
    </Tooltip>
  );
}

export { SelectButton, type SelectButtonProps };
