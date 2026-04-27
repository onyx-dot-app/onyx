import {
  Interactive,
  type InteractiveStatefulInteraction,
  type InteractiveStatefulProps,
} from "@opal/core";
import { Text, Tooltip, Button, type TooltipSide } from "@opal/components";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { SvgX } from "@opal/icons";
import { iconWrapper } from "@opal/components/buttons/icon-wrapper";
import { ChevronIcon } from "@opal/components/buttons/chevron";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FilterButtonProps
  extends Omit<InteractiveStatefulProps, "variant" | "state" | "children"> {
  /** Left icon — always visible. */
  icon: IconFunctionComponent;

  /** Label text between icon and trailing indicator. */
  children: string | RichStr;

  /** Whether the filter has an active selection. @default false */
  active?: boolean;

  /** Called when the clear (X) button is clicked in active state. */
  onClear: () => void;

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
  active = false,
  interaction,
  ...statefulProps
}: FilterButtonProps) {
  // Derive open state: explicit prop > Radix data-state (injected via Slot chain)
  const dataState = (statefulProps as Record<string, unknown>)["data-state"] as
    | string
    | undefined;
  const resolvedInteraction: InteractiveStatefulInteraction =
    interaction ?? (dataState === "open" ? "hover" : "rest");

  const button = (
    <div className="relative">
      <Interactive.Stateful
        {...statefulProps}
        variant="select-filter"
        interaction={resolvedInteraction}
        state={active ? "selected" : "empty"}
      >
        <Interactive.Container type="button">
          <div className="flex flex-row items-center gap-1">
            {iconWrapper(Icon, "lg", true)}
            <Text font="main-ui-action" color="inherit" nowrap>
              {children}
            </Text>
            <div style={{ visibility: active ? "hidden" : "visible" }}>
              {iconWrapper(ChevronIcon, "lg", true)}
            </div>
          </div>
        </Interactive.Container>
      </Interactive.Stateful>

      {active && (
        <div className="absolute right-2 top-1/2 -translate-y-1/2">
          {/* Force hover state so the X stays visually prominent against
              the inverted selected background — without this it renders
              dimmed and looks disabled. */}
          <Button
            icon={SvgX}
            size="2xs"
            prominence="tertiary"
            tooltip="Clear filter"
            interaction="hover"
            onClick={(e) => {
              e.stopPropagation();
              onClear();
            }}
          />
        </div>
      )}
    </div>
  );

  return (
    <Tooltip tooltip={tooltip} side={tooltipSide}>
      {button}
    </Tooltip>
  );
}

export { FilterButton, type FilterButtonProps };
