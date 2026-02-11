import "@opal/components/buttons/OpenButton/styles.css";
import { Button } from "@opal/components/buttons/Button/components";
import type { ButtonProps } from "@opal/components";
import { SvgChevronDownSmall } from "@opal/icons";
import { cn } from "@opal/utils";
import type { InteractiveBaseVariantProps } from "@opal/core";
import type { InteractiveBaseSelectVariantProps } from "@opal/core/interactive/components";
import type { IconProps } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Omit that distributes over unions, preserving discriminated-union branches. */
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown
  ? Omit<T, K>
  : never;

type OpenButtonProps = DistributiveOmit<
  ButtonProps,
  keyof InteractiveBaseVariantProps
> &
  InteractiveBaseSelectVariantProps;

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
// OpenButton
// ---------------------------------------------------------------------------

function OpenButton({ transient, ...baseProps }: OpenButtonProps) {
  // Derive open state: explicit prop → Radix data-state (injected via Slot chain)
  const dataState = (baseProps as Record<string, unknown>)["data-state"] as
    | string
    | undefined;
  const transient_ = transient ?? dataState === "open";

  // Assertion is safe: OpenButton is a controlled wrapper that always supplies
  // rightIcon (ChevronIcon) and variant="select", satisfying Button's union.
  const buttonProps = {
    ...baseProps,
    variant: "select" as const,
    transient: transient_,
    rightIcon: ChevronIcon,
  } as ButtonProps;

  return <Button {...buttonProps} />;
}

export { OpenButton, type OpenButtonProps };
