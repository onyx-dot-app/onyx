import "@opal/core/disabled/styles.css";
import React, { createContext, useContext } from "react";

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

interface DisabledState {
  isDisabled: boolean;
  allowClick: boolean;
}

const DisabledContext = createContext<DisabledState>({
  isDisabled: false,
  allowClick: false,
});

/**
 * Returns the disabled state from the nearest `<Disabled>` ancestor.
 *
 * Components use this to implement JS-level disabled behaviour (blocking
 * onClick, suppressing href navigation, setting `aria-disabled`, etc.)
 * without accepting a `disabled` prop of their own.
 */
function useDisabled(): DisabledState {
  return useContext(DisabledContext);
}

// ---------------------------------------------------------------------------
// Disabled component
// ---------------------------------------------------------------------------

interface DisabledProps {
  /** Whether the children are disabled. @default false */
  disabled?: boolean;

  /**
   * When `true`, pointer events are **not** blocked — only visual styling is
   * applied. Useful when a disabled element still needs to respond to hovers
   * (e.g. to show a tooltip explaining *why* it is disabled).
   *
   * @default false
   */
  allowClick?: boolean;

  children: React.ReactNode;

  /** Forwarded ref. */
  ref?: React.Ref<HTMLDivElement>;
}

/**
 * Wrapper that marks its children as disabled.
 *
 * Renders a `display: contents` `<div>` so it adds no layout. When `disabled`
 * is `true`, baseline CSS (opacity, cursor, pointer-events) is applied to
 * direct children. Components that consume `useDisabled()` can layer on their
 * own disabled styling.
 *
 * @example
 * ```tsx
 * import { Disabled } from "@opal/core";
 *
 * <Disabled disabled={isSubmitting}>
 *   <Button type="submit">Save</Button>
 * </Disabled>
 * ```
 */
function Disabled({ disabled, allowClick, children, ref }: DisabledProps) {
  return (
    <DisabledContext.Provider
      value={{ isDisabled: !!disabled, allowClick: !!allowClick }}
    >
      <div
        ref={ref}
        className="opal-disabled"
        data-disabled={disabled || undefined}
        data-allow-click={disabled && allowClick ? "" : undefined}
      >
        {children}
      </div>
    </DisabledContext.Provider>
  );
}

export { Disabled, type DisabledProps, useDisabled };
