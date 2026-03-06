import "@opal/components/buttons/open-button/styles.css";
import "@opal/components/tooltip.css";
import {
  Interactive,
  type InteractiveStatefulProps,
  type InteractiveStatefulInteraction,
} from "@opal/core";
import type { SizeVariant, WidthVariant } from "@opal/shared";
import type { TooltipSide } from "@opal/components";
import type { IconFunctionComponent, IconProps } from "@opal/types";
import { SvgChevronDownSmall } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Chevron (stable identity — never causes React to remount the SVG)
// ---------------------------------------------------------------------------

function ChevronIcon({ className, ...props }: IconProps) {
  return (
    <SvgChevronDownSmall
      className={cn(className, "opal-open-button-chevron")}
      {...props}
    />
  );
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type OpenButtonProps = Omit<InteractiveStatefulProps, "variant"> & {
  /** Left icon. */
  icon?: IconFunctionComponent;

  /** Button label text. */
  children?: string;

  /**
   * Size preset — controls gap, text size, and Container height/rounding.
   */
  size?: SizeVariant;

  /** Width preset. */
  width?: WidthVariant;

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
  size = "lg",
  width,
  tooltip,
  tooltipSide = "top",
  interaction,
  ...statefulProps
}: OpenButtonProps) {
  // Derive open state: explicit prop → Radix data-state (injected via Slot chain)
  const dataState = (statefulProps as Record<string, unknown>)["data-state"] as
    | string
    | undefined;
  const resolvedInteraction: InteractiveStatefulInteraction =
    interaction ?? (dataState === "open" ? "hover" : "rest");

  const isLarge = size === "lg";

  const button = (
    <Interactive.Stateful
      variant="select-heavy"
      interaction={resolvedInteraction}
      {...statefulProps}
    >
      <Interactive.Container
        type="button"
        heightVariant={size}
        widthVariant={width}
        roundingVariant={
          isLarge ? "default" : size === "2xs" ? "mini" : "compact"
        }
      >
        <div className="opal-button interactive-foreground flex flex-row items-center gap-1">
          {Icon && (
            <div className="interactive-foreground-icon p-0.5">
              <Icon className="shrink-0 h-[1rem] w-[1rem]" />
            </div>
          )}
          {children && (
            <span
              className={cn(
                "opal-button-label whitespace-nowrap",
                isLarge ? "font-main-ui-body" : "font-secondary-body"
              )}
            >
              {children}
            </span>
          )}
          <div className="interactive-foreground-icon p-0.5">
            <ChevronIcon className="shrink-0 h-[1rem] w-[1rem]" />
          </div>
        </div>
      </Interactive.Container>
    </Interactive.Stateful>
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
