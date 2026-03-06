import "@opal/core/disabled/styles.css";
import React, { createContext, useContext } from "react";
import { Slot } from "@radix-ui/react-slot";

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

interface DisabledContextValue {
  isDisabled: boolean;
  allowClick: boolean;
}

const DisabledContext = createContext<DisabledContextValue>({
  isDisabled: false,
  allowClick: false,
});

/**
 * Returns the current disabled state from the nearest `<Disabled>` ancestor.
 *
 * Used internally by `Interactive.Stateless` and `Interactive.Stateful` to
 * derive `data-disabled` and `aria-disabled` attributes automatically.
 */
function useDisabled(): DisabledContextValue {
  return useContext(DisabledContext);
}

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
 * Wrapper component that propagates disabled state via context and applies
 * baseline disabled CSS (opacity, cursor, pointer-events) to its child.
 *
 * Uses Radix `Slot` — merges props onto the single child element without
 * adding any DOM node. Works correctly inside Radix `asChild` chains.
 *
 * @example
 * ```tsx
 * <Disabled disabled={!canSubmit}>
 *   <Button onClick={handleSubmit}>Save</Button>
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
    <DisabledContext.Provider
      value={{ isDisabled: !!disabled, allowClick: !!allowClick }}
    >
      <Slot
        ref={ref}
        {...rest}
        data-opal-disabled={disabled || undefined}
        data-allow-click={disabled && allowClick ? "" : undefined}
      >
        {children}
      </Slot>
    </DisabledContext.Provider>
  );
}

export { Disabled, useDisabled, type DisabledProps, type DisabledContextValue };
