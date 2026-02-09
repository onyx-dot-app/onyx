import "@opal/components/buttons/Button/styles.css";
import "@opal/components/tooltip.css";
import { Interactive, type InteractiveBaseProps } from "@opal/core";
import type { SizeVariant, TooltipSide } from "@opal/components";
import type { IconFunctionComponent } from "@opal/types";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ButtonProps = InteractiveBaseProps & {
  /** Left icon component (renders at 1rem x 1rem). */
  icon?: IconFunctionComponent;

  /** Button label text. Omit for icon-only buttons. */
  children?: string;

  /** Right icon component (renders at 1rem x 1rem). */
  rightIcon?: IconFunctionComponent;

  /** Size preset — controls gap, text size, and Container height/rounding. */
  size?: SizeVariant;

  /** Tooltip text shown on hover. */
  tooltip?: string;

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
  size = "default",
  tooltip,
  tooltipSide = "top",
  variant,
  subvariant,
  ...baseProps
}: ButtonProps) {
  const isCompact = size === "compact";

  const button = (
    <Interactive.Base
      {...({ variant, subvariant } as InteractiveBaseProps)}
      {...baseProps}
    >
      <Interactive.Container
        heightVariant={isCompact ? "compact" : "default"}
        roundingVariant={isCompact ? "compact" : "default"}
        paddingVariant={isCompact ? "thin" : "default"}
      >
        <div
          className="opal-button interactive-foreground"
          data-size={isCompact ? "compact" : undefined}
        >
          {Icon && <Icon className="opal-button-icon" />}
          {children && <span className="opal-button-label">{children}</span>}
          {RightIcon && <RightIcon className="opal-button-icon" />}
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
