"use client";

import "@opal/components/inputs/switch/styles.css";
import React, { useState } from "react";
import { cn } from "@opal/utils";
import type { WithoutStyles } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SwitchProps extends WithoutStyles<
  Omit<React.ComponentPropsWithoutRef<"button">, "onChange">
> {
  disabled?: boolean;
  checked?: boolean;
  defaultChecked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Accessible toggle switch. Supports controlled and uncontrolled modes.
 *
 * - Controlled: pass `checked` + `onCheckedChange`.
 * - Uncontrolled: pass `defaultChecked` (defaults to `false`).
 */
const Switch = React.forwardRef<HTMLButtonElement, SwitchProps>(
  (
    {
      disabled,
      checked: controlledChecked,
      defaultChecked,
      onCheckedChange,
      onClick,
      ...props
    },
    ref
  ) => {
    const [uncontrolledChecked, setUncontrolledChecked] = useState(
      defaultChecked ?? false
    );

    const isControlled = controlledChecked !== undefined;
    const checked = isControlled ? controlledChecked : uncontrolledChecked;

    function handleClick(event: React.MouseEvent<HTMLButtonElement>) {
      if (disabled) return;

      const newChecked = !checked;

      if (!isControlled) setUncontrolledChecked(newChecked);
      onClick?.(event);
      onCheckedChange?.(newChecked);
    }

    return (
      <button
        ref={ref}
        type="button"
        role="switch"
        aria-checked={checked}
        className={cn(
          "peer inline-flex h-4.5 w-8 shrink-0 cursor-pointer items-center rounded-full transition-colors focus-visible:outline-hidden",
          disabled
            ? checked
              ? "switch-disabled-checked"
              : "switch-disabled"
            : checked
              ? "switch-normal-checked"
              : "switch-normal"
        )}
        disabled={disabled}
        onClick={handleClick}
        {...props}
      >
        <span
          className={cn(
            "pointer-events-none block h-3.5 w-3.5 rounded-full ring-0 transition-transform",
            checked ? "translate-x-[15px]" : "translate-x-px",
            disabled ? "switch-thumb-disabled" : "switch-thumb"
          )}
        />
      </button>
    );
  }
);
Switch.displayName = "Switch";

export default Switch;
export { Switch };
