import "@opal/components/tooltip.css";
import {
  Disabled,
  Interactive,
  type InteractiveStatelessProps,
} from "@opal/core";
import type {
  ContainerSizeVariants,
  ExtremaSizeVariants,
  RichStr,
} from "@opal/types";
import { Text } from "@opal/components/text/components";
import type { TooltipSide } from "@opal/components";
import type { IconFunctionComponent } from "@opal/types";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { iconWrapper } from "@opal/components/buttons/icon-wrapper";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ButtonContentProps =
  | {
      icon?: IconFunctionComponent;
      children: string | RichStr;
      rightIcon?: IconFunctionComponent;
      responsiveHideText?: never;
    }
  | {
      icon: IconFunctionComponent;
      children?: string | RichStr;
      rightIcon?: IconFunctionComponent;
      responsiveHideText?: boolean;
    };

type ButtonProps = InteractiveStatelessProps &
  ButtonContentProps & {
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

    /** Wraps the button in a Disabled context. `false` overrides parent contexts. */
    disabled?: boolean;
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
  disabled,
  ...interactiveProps
}: ButtonProps) {
  const isLarge = size === "lg";

  const labelEl = children ? (
    responsiveHideText ? (
      <span className="hidden md:inline whitespace-nowrap">
        <Text font={isLarge ? "main-ui-body" : "secondary-body"}>
          {children}
        </Text>
      </span>
    ) : (
      <Text font={isLarge ? "main-ui-body" : "secondary-body"} nowrap>
        {children}
      </Text>
    )
  ) : null;

  const button = (
    <Interactive.Stateless type={type} {...interactiveProps}>
      <Interactive.Container
        type={type}
        border={interactiveProps.prominence === "secondary"}
        heightVariant={size}
        widthVariant={width}
        roundingVariant={
          isLarge ? "default" : size === "2xs" ? "mini" : "compact"
        }
      >
        <div className="flex flex-row items-center gap-1 interactive-foreground">
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

  const result = tooltip ? (
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
  ) : (
    button
  );

  if (disabled != null) {
    return <Disabled disabled={disabled}>{result}</Disabled>;
  }

  return result;
}

export { Button, type ButtonProps };
