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
import { Button } from "@opal/components/buttons/button/components";

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
  // Derive open state: explicit prop > bounding-box hover > Radix data-state
  const dataState = (statefulProps as Record<string, unknown>)["data-state"] as
    | string
    | undefined;
  const resolvedInteraction: InteractiveStatefulInteraction =
    statefulProps.interaction ?? dataState === "open" ? "hover" : "rest";

  const isSelected = statefulProps.state === "selected";

  const button = (
    <div className="relative">
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
            {isSelected ? (
              /* Invisible spacer — reserves the same space as the chevron
                 so the absolutely-positioned clear Button overlays it
                 without shifting layout. */
              <div className="p-2" aria-hidden />
            ) : (
              iconWrapper(ChevronIcon, "lg", true)
            )}
          </div>
        </Interactive.Container>
      </Interactive.Stateful>

      {isSelected && (
        <div className="absolute right-2 top-1/2 -translate-y-1/2">
          <Button
            icon={SvgX}
            size="2xs"
            prominence="tertiary"
            tooltip="Clear filter"
            interaction="hover"
            onClick={(e) => {
              e.stopPropagation();
              onClear?.();
            }}
          />
        </div>
      )}
    </div>
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
