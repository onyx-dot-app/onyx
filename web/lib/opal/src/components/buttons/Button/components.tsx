import "@opal/components/buttons/Button/styles.css";
import "@opal/components/tooltip.css";
import { Interactive, type InteractiveBaseProps } from "@opal/core";
import type { SizeVariant, TooltipSide } from "@opal/components";
import type { IconFunctionComponent } from "@opal/types";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { cn } from "@opal/utils";

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
type ButtonContentProps =
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

type ButtonProps = InteractiveBaseProps &
  ButtonContentProps & {
    /** Size preset — controls gap, text size, and Container height/rounding. */
    size?: SizeVariant;

    /** HTML button type. When provided, Container renders a `<button>` element. */
    type?: "submit" | "button" | "reset";

    /** Tooltip text shown on hover. */
    tooltip?: string;

    /** Which side the tooltip appears on. */
    tooltipSide?: TooltipSide;
  };

function iconWrapper(
  Icon: IconFunctionComponent | undefined,
  isCompact: boolean,
  includeSpacer: boolean
) {
  return Icon ? (
    <div className="p-0.5 interactive-foreground-icon">
      <Icon
        className={cn(
          "shrink-0",
          isCompact ? "h-[0.75rem] w-[0.75rem]" : "h-[1rem] w-[1rem]"
        )}
        size={isCompact ? 12 : 16}
      />
    </div>
  ) : includeSpacer ? (
    <div />
  ) : null;
}

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------

function Button({
  icon: Icon,
  children,
  rightIcon: RightIcon,
  size = "default",
  foldable,
  type,
  tooltip,
  tooltipSide = "top",
  ...interactiveBaseProps
}: ButtonProps) {
  const isCompact = size === "compact";

  const labelEl = children ? (
    <span
      className={cn(
        "opal-button-label",
        isCompact ? "font-secondary-body" : "font-main-ui-body"
      )}
    >
      {children}
    </span>
  ) : null;

  const button = (
    <Interactive.Base {...interactiveBaseProps}>
      <Interactive.Container
        type={interactiveBaseProps.href ? undefined : type}
        border={interactiveBaseProps.prominence === "secondary"}
        heightVariant={isCompact ? "md" : "lg"}
        roundingVariant={isCompact ? "compact" : "default"}
      >
        <div
          className={cn(
            "opal-button interactive-foreground",
            foldable && "opal-button--foldable"
          )}
        >
          {iconWrapper(Icon, isCompact, !foldable && !!children)}

          {foldable ? (
            <div className="opal-button-foldable">
              <div className="opal-button-foldable-inner">
                {labelEl}
                {iconWrapper(RightIcon, isCompact, !!children)}
              </div>
            </div>
          ) : (
            <>
              {labelEl}
              {iconWrapper(RightIcon, isCompact, !!children)}
            </>
          )}
        </div>
      </Interactive.Container>
    </Interactive.Base>
  );

  if (!tooltip) return button;

  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{button}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          className="opal-tooltip"
          side={tooltipSide}
          sideOffset={4}
        >
          {tooltip}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export { Button, type ButtonProps };
