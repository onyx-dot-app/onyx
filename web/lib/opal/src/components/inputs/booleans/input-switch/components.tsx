"use client";

import "@opal/components/inputs/booleans/input-switch/styles.css";
import React, { useState } from "react";
import { cn } from "@opal/utils";
import type { WithoutStyles } from "@opal/types";

/**
 * Accessible toggle switch. Supports controlled and uncontrolled modes.
 *
 * - Controlled: pass `checked` + `onCheckedChange`.
 * - Uncontrolled: pass `defaultChecked` (defaults to `false`).
 */
type InputSwitchProps = WithoutStyles<
  Omit<React.ComponentPropsWithoutRef<"button">, "onChange" | "type">
> & {
  disabled?: boolean;
  checked?: boolean;
  defaultChecked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  /** Ref to the switch `<button>`. */
  ref?: React.Ref<HTMLButtonElement>;
};
function InputSwitch({
  ref,
  disabled,
  checked: controlledChecked,
  defaultChecked,
  onCheckedChange,
  onClick,
  ...props
}: InputSwitchProps) {
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
      // Spread first: type/role/aria-checked/disabled/onClick are this
      // control's contract and must not be overridable through the spread.
      {...props}
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
    >
      <span
        className={cn(
          "pointer-events-none block h-3.5 w-3.5 rounded-full ring-0 transition-transform",
          // rtl: the knob travels toward the inline end, so RTL negates.
          checked
            ? "translate-x-[15px] rtl:-translate-x-[15px]"
            : "translate-x-px rtl:-translate-x-px",
          disabled ? "switch-thumb-disabled" : "switch-thumb"
        )}
      />
    </button>
  );
}

export { InputSwitch, type InputSwitchProps };
