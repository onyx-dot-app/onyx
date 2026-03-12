import "@opal/components/buttons/open-button/styles.css";
import "@opal/components/tooltip.css";
import {
  Interactive,
  useDisabled,
  type InteractiveStatefulProps,
  type InteractiveStatefulInteraction,
} from "@opal/core";
import type { SizeVariant, WidthVariant } from "@opal/shared";
import type { TooltipSide } from "@opal/components";
import type { IconFunctionComponent, IconProps } from "@opal/types";
import { SvgChevronDownSmall } from "@opal/icons";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { cn } from "@opal/utils";
import { iconWrapper } from "@opal/components/buttons/icon-wrapper";

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

/**
 * Content props — a discriminated union on `foldable` that enforces:
 *
 * - `foldable: true`  → `icon` and `children` are required (icon stays visible,
 *                        label + chevron fold away)
 * - `foldable?: false` → at least one of `icon` or `children` must be provided
 */
type OpenButtonContentProps =
  | {
      foldable: true;
      icon: IconFunctionComponent;
      children: string;
    }
  | {
      foldable?: false;
      icon?: IconFunctionComponent;
      children: string;
    }
  | {
      foldable?: false;
      icon: IconFunctionComponent;
      children?: string;
    };

type OpenButtonVariant = "select-light" | "select-heavy" | "select-tinted";

type OpenButtonProps = Omit<InteractiveStatefulProps, "variant"> & {
  variant?: OpenButtonVariant;
} & OpenButtonContentProps & {
    /**
     * Size preset — controls gap, text size, and Container height/rounding.
     */
    size?: SizeVariant;

    /** Width preset. */
    width?: WidthVariant;

    /**
     * Content justify mode. When `"between"`, icon+label group left and
     * chevron pushes to the right edge. Default keeps all items in a
     * tight `gap-1` row.
     */
    justifyContent?: "between";

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
  foldable,
  width,
  justifyContent,
  tooltip,
  tooltipSide = "top",
  interaction,
  variant = "select-heavy",
  ...statefulProps
}: OpenButtonProps) {
  const { isDisabled } = useDisabled();

  // Derive open state: explicit prop → Radix data-state (injected via Slot chain)
  const dataState = (statefulProps as Record<string, unknown>)["data-state"] as
    | string
    | undefined;
  const resolvedInteraction: InteractiveStatefulInteraction =
    interaction ?? (dataState === "open" ? "hover" : "rest");

  const isLarge = size === "lg";

  const labelEl = children ? (
    <span
      className={cn(
        "opal-button-label whitespace-nowrap",
        isLarge ? "font-main-ui-body" : "font-secondary-body"
      )}
    >
      {children}
    </span>
  ) : null;

  const button = (
    <Interactive.Stateful
      variant={variant}
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
        <div
          className={cn(
            "opal-button interactive-foreground flex flex-row items-center",
            justifyContent === "between" ? "w-full justify-between" : "gap-1",
            foldable &&
              justifyContent !== "between" &&
              "interactive-foldable-host"
          )}
        >
          {justifyContent === "between" ? (
            <>
              <span className="flex flex-row items-center gap-1">
                {iconWrapper(Icon, size, !foldable && !!children)}
                {labelEl}
              </span>
              {iconWrapper(ChevronIcon, size, !!children)}
            </>
          ) : foldable ? (
            <>
              {iconWrapper(Icon, size, !foldable && !!children)}
              <Interactive.Foldable>
                {labelEl}
                {iconWrapper(ChevronIcon, size, !!children)}
              </Interactive.Foldable>
            </>
          ) : (
            <>
              {iconWrapper(Icon, size, !foldable && !!children)}
              {labelEl}
              {iconWrapper(ChevronIcon, size, !!children)}
            </>
          )}
        </div>
      </Interactive.Container>
    </Interactive.Stateful>
  );

  const resolvedTooltip =
    tooltip ?? (foldable && isDisabled && children ? children : undefined);

  if (!resolvedTooltip) return button;

  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{button}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          className="opal-tooltip"
          side={tooltipSide}
          sideOffset={4}
        >
          {resolvedTooltip}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export { OpenButton, type OpenButtonProps };
