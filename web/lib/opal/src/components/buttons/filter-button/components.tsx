import {
  Interactive,
  type InteractiveStatefulInteraction,
  type InteractiveStatefulState,
  type InteractiveStatefulProps,
} from "@opal/core";
import type { TooltipSide } from "@opal/components";
import type { IconFunctionComponent } from "@opal/types";
import { SvgX } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { iconWrapper } from "@opal/components/buttons/icon-wrapper";
import { ChevronIcon } from "@opal/components/buttons/chevron";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FilterButtonProps
  extends Omit<InteractiveStatefulProps, "variant" | "state"> {
  /** Left icon — always visible. */
  icon: IconFunctionComponent;

  /** Label text between icon and trailing indicator. */
  children: string;

  /** Whether the filter is active (has a selection). */
  state?: Extract<InteractiveStatefulState, "empty" | "selected">;

  /** Called when the clear (X) button is clicked in active state. */
  onClear?: () => void;

  /** Tooltip text shown on hover. */
  tooltip?: string;

  /** Which side the tooltip appears on. */
  tooltipSide?: TooltipSide;
}

// ---------------------------------------------------------------------------
// FilterButton
// ---------------------------------------------------------------------------

function FilterButton({
  icon: Icon,
  children,
  onClear,
  tooltip,
  tooltipSide = "top",
  ...statefulProps
}: FilterButtonProps) {
  // Derive open state: explicit prop > Radix data-state (injected via Slot chain)
  const dataState = (statefulProps as Record<string, unknown>)["data-state"] as
    | string
    | undefined;
  const resolvedInteraction: InteractiveStatefulInteraction =
    statefulProps.interaction ?? (dataState === "open" ? "hover" : "rest");

  const button = (
    <Interactive.Stateful
      variant="select-filter"
      interaction={resolvedInteraction}
      state={statefulProps.state}
      {...statefulProps}
    >
      <Interactive.Container type="button">
        <div className="interactive-foreground flex flex-row items-center gap-1">
          {iconWrapper(Icon, "lg", true)}
          <span className="whitespace-nowrap font-main-ui-action">
            {children}
          </span>
          {statefulProps.state === "selected" ? (
            <div
              role="button"
              aria-label="Clear filter"
              className="interactive-foreground-icon p-0.5 rounded-04 hover:bg-background-tint-02 active:bg-background-neutral-00"
              onClick={(e) => {
                e.stopPropagation();
                onClear?.();
              }}
            >
              <SvgX
                className="shrink-0"
                style={{ height: "0.75rem", width: "0.75rem" }}
              />
            </div>
          ) : (
            iconWrapper(ChevronIcon, "lg", true)
          )}
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

export { FilterButton, type FilterButtonProps };
