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

function iconWrapper(
  Icon: IconFunctionComponent | undefined,
  isCompact: boolean
) {
  return Icon ? (
    <div className="p-0.5">
      <Icon
        className={cn(
          "shrink-0",
          isCompact ? "h-[0.75rem] w-[0.75rem]" : "h-[1rem] w-[1rem]"
        )}
        size={isCompact ? 12 : 16}
      />
    </div>
  ) : (
    <div className="w-[0.125rem]" />
  );
}

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
  ...interactiveBaseProps
}: ButtonProps) {
  const isCompact = size === "compact";

  const button = (
    <Interactive.Base {...interactiveBaseProps}>
      <Interactive.Container
        border={interactiveBaseProps.subvariant === "secondary"}
        heightVariant={isCompact ? "compact" : "default"}
        roundingVariant={isCompact ? "compact" : "default"}
        paddingVariant={isCompact ? "thin" : "default"}
      >
        <div className="opal-button interactive-foreground">
          {iconWrapper(Icon, isCompact)}
          {children && (
            <span
              className={cn(
                "opal-button-label",
                isCompact ? "font-secondary-action" : "font-main-ui-action"
              )}
            >
              {children}
            </span>
          )}
          {iconWrapper(RightIcon, isCompact)}
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
