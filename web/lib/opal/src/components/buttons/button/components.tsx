import "@opal/components/buttons/button/styles.css";
import "@opal/components/tooltip.css";
import { Interactive, type InteractiveStatelessProps } from "@opal/core";
import type { ContainerSizeVariants, ExtremaSizeVariants } from "@opal/shared";
import type { TooltipSide } from "@opal/components";
import type { IconFunctionComponent } from "@opal/types";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { cn } from "@opal/utils";
import { iconWrapper } from "@opal/components/buttons/icon-wrapper";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ButtonContentProps =
  | {
      icon?: IconFunctionComponent;
      children: string;
      rightIcon?: IconFunctionComponent;
      responsiveHideText?: never;
    }
  | {
      icon: IconFunctionComponent;
      children?: string;
      rightIcon?: IconFunctionComponent;
      responsiveHideText?: boolean;
    };

type ButtonProps = InteractiveStatelessProps &
  ButtonContentProps & {
    /**
     * Size preset — controls gap, text size, and Container height/rounding.
     */
    size?: ContainerSizeVariants;

    /** HTML button type. When provided, Container renders a `<button>` element. */
    type?: "submit" | "button" | "reset";

    /** Tooltip text shown on hover. */
    tooltip?: string;

    /** Width preset. `"fit"` shrink-wraps, `"full"` stretches to parent width. */
    width?: ExtremaSizeVariants;

    /** Which side the tooltip appears on. */
    tooltipSide?: TooltipSide;
  };

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------

function Button({
  icon: Icon,
  children,
  rightIcon: RightIcon,
  size = "lg",
  type = "button",
  width,
  tooltip,
  tooltipSide = "top",
  responsiveHideText = false,
  ...interactiveProps
}: ButtonProps) {
  const isLarge = size === "lg";

  const labelEl = children ? (
    <span
      className={cn(
        "opal-button-label",
        isLarge ? "font-main-ui-body " : "font-secondary-body",
        responsiveHideText && "hidden md:inline"
      )}
    >
      {children}
    </span>
  ) : null;

  const button = (
    <Interactive.Stateless {...interactiveProps}>
      <Interactive.Container
        type={type}
        border={interactiveProps.prominence === "secondary"}
        heightVariant={size}
        widthVariant={width}
        roundingVariant={
          isLarge ? "default" : size === "2xs" ? "mini" : "compact"
        }
      >
        <div className={cn("opal-button interactive-foreground")}>
          {iconWrapper(Icon, size, !!children)}

          {labelEl}
          {responsiveHideText ? (
            <span className="hidden md:inline-flex">
              {iconWrapper(RightIcon, size, !!children)}
            </span>
          ) : (
            iconWrapper(RightIcon, size, !!children)
          )}
        </div>
      </Interactive.Container>
    </Interactive.Stateless>
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
