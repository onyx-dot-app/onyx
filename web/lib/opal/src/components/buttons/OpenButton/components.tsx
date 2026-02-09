import "@opal/components/buttons/OpenButton/styles.css";
import "@opal/components/tooltip.css";
import { Interactive, type InteractiveBaseProps } from "@opal/core";
import type { SizeVariant, TooltipSide } from "@opal/components";
import { SvgChevronDownSmall } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type OpenButtonProps = InteractiveBaseProps & {
  /** Left icon component (renders at 1rem x 1rem). */
  icon?: IconFunctionComponent;

  /** Content rendered between the icon and chevron. */
  children?: string;

  /** When `true`, applies a 1px border to the container. */
  border?: boolean;

  /** Size preset — controls Container height/rounding/padding. */
  size?: SizeVariant;

  /** Tooltip text shown on hover. */
  tooltip?: string;

  /** Which side the tooltip appears on. */
  tooltipSide?: TooltipSide;
};

// ---------------------------------------------------------------------------
// OpenButton
// ---------------------------------------------------------------------------

function OpenButton({
  icon: Icon,
  children,
  border,
  selected,
  size = "default",
  tooltip,
  tooltipSide = "top",
  variant,
  subvariant,
  ...baseProps
}: OpenButtonProps) {
  // Derive open state: explicit prop → Radix data-state (injected via Slot chain)
  const dataState = (baseProps as Record<string, unknown>)["data-state"] as
    | string
    | undefined;
  const isOpen = selected ?? dataState === "open";
  const isCompact = size === "compact";

  const button = (
    <Interactive.Base
      {...({ variant, subvariant } as InteractiveBaseProps)}
      selected={isOpen}
      {...baseProps}
    >
      <Interactive.Container
        border={border}
        heightVariant={isCompact ? "compact" : "default"}
        roundingVariant={isCompact ? "compact" : "default"}
        paddingVariant={isCompact ? "thin" : "default"}
      >
        <div className="opal-open-button interactive-foreground">
          {Icon && <Icon className="opal-open-button-icon" />}
          <div className="opal-open-button-content">{children}</div>
          <SvgChevronDownSmall
            className="opal-open-button-chevron"
            data-selected={isOpen ? "true" : undefined}
            size={14}
          />
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

export { OpenButton, type OpenButtonProps };
