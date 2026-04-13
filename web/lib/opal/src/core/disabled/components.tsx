import "@opal/core/disabled/styles.css";
import React from "react";
import { Slot } from "@radix-ui/react-slot";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DisabledProps extends React.HTMLAttributes<HTMLElement> {
  ref?: React.Ref<HTMLElement>;

  /**
   * When truthy, applies disabled styling to child elements.
   */
  disabled?: boolean;

  /**
   * When `true`, re-enables pointer events while keeping the disabled
   * visual treatment. Useful for elements that need to show tooltips or
   * error messages on click.
   * @default false
   */
  allowClick?: boolean;

  children: React.ReactElement;
}

// ---------------------------------------------------------------------------
// Disabled
// ---------------------------------------------------------------------------

/**
 * Wrapper component that applies baseline disabled CSS (opacity, cursor,
 * pointer-events) to its child element.
 *
 * Uses Radix `Slot` — merges props onto the single child element without
 * adding any DOM node. Works correctly inside Radix `asChild` chains.
 *
 * @example
 * ```tsx
 * <Disabled disabled={!canSubmit}>
 *   <div>...</div>
 * </Disabled>
 * ```
 */
function Disabled({
  disabled,
  allowClick,
  children,
  ref,
  ...rest
}: DisabledProps) {
  return (
    <Slot
      ref={ref}
      {...rest}
      aria-disabled={disabled || undefined}
      data-opal-disabled={disabled || undefined}
      data-allow-click={disabled && allowClick ? "" : undefined}
    >
      {children}
    </Slot>
  );
}

export { Disabled, type DisabledProps };
