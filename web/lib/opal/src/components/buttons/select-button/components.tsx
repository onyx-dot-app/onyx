import "@opal/components/buttons/select-button/styles.css";
import "@opal/components/tooltip.css";
import { Interactive, type InteractiveStatefulProps } from "@opal/core";
import type { SizeVariant, WidthVariant } from "@opal/shared";
import type { TooltipSide } from "@opal/components";
import type { IconFunctionComponent } from "@opal/types";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
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
      children: string;
      rightIcon?: IconFunctionComponent;
    }
  | {
      foldable?: false;
      icon?: IconFunctionComponent;
      children: string;
      rightIcon?: IconFunctionComponent;
    }
  | {
      foldable?: false;
      icon: IconFunctionComponent;
      children?: string;
      rightIcon?: IconFunctionComponent;
    };

type SelectButtonProps = InteractiveStatefulProps &
  SelectButtonContentProps & {
    /**
     * Size preset — controls gap, text size, and Container height/rounding.
     */
    size?: SizeVariant;

    /** HTML button type. Container renders a `<button>` element. */
    type?: "submit" | "button" | "reset";

    /** Tooltip text shown on hover. */
    tooltip?: string;

    /** Width preset. `"auto"` shrink-wraps, `"full"` stretches to parent width. */
    width?: WidthVariant;

    /** Which side the tooltip appears on. */
    tooltipSide?: TooltipSide;
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
  ...statefulProps
}: SelectButtonProps) {
  const isLarge = size === "lg";

  const labelEl = children ? (
    <span
      className={cn(
        "opal-select-button-label",
        isLarge ? "font-main-ui-body" : "font-secondary-body"
      )}
    >
      {children}
    </span>
  ) : null;

  const button = (
    <Interactive.Stateful {...statefulProps}>
      <Interactive.Container
        type={type}
        heightVariant={size}
        widthVariant={width}
        roundingVariant={
          isLarge ? "default" : size === "2xs" ? "mini" : "compact"
        }
      >
        <div
          className={cn(
            "opal-select-button interactive-foreground",
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
    tooltip ??
    (foldable && statefulProps.disabled && children ? children : undefined);

  if (!resolvedTooltip) return button;

  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{button}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          className="opal-tooltip"
          side={tooltipSide}
          sideOffset={4}
        >
          {resolvedTooltip}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export { SelectButton, type SelectButtonProps };
