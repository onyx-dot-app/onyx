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

type OpenButtonProps = Omit<ButtonProps, keyof InteractiveBaseVariantProps> &
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

  return (
    <Button
      variant="select"
      transient={transient_}
      rightIcon={ChevronIcon}
      {...baseProps}
    />
  );
}

export { OpenButton, type OpenButtonProps };
