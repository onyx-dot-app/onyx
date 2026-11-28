"use client";

import "@opal/components/inputs/booleans/input-switch/styles.css";
import React, { useState } from "react";
import { cn } from "@opal/utils";
import type { RichStr, WithoutStyles } from "@opal/types";
import {
  InputTooltip,
  useInputDisabled,
} from "@opal/components/inputs/disabled";

/**
 * Accessible toggle switch. Supports controlled and uncontrolled modes.
 *
 * - Controlled: pass `checked` + `onCheckedChange`.
 * - Uncontrolled: pass `defaultChecked` (defaults to `false`).
 *
 * Inside `InputHorizontal` or `InputVertical`, the row's `disabled` and
 * `disabledTooltip` apply to it too.
 */
type InputSwitchProps = WithoutStyles<
  Omit<React.ComponentPropsWithoutRef<"button">, "onChange" | "type">
> & {
  disabled?: boolean;
  /** Shown on hover, in any state. A disabled row's reason replaces it. */
  tooltip?: string | RichStr;
  checked?: boolean;
  defaultChecked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  /** Ref to the switch `<button>`. */
  ref?: React.Ref<HTMLButtonElement>;
};
function InputSwitch({
  ref,
  disabled: disabledProp,
  tooltip,
  checked: controlledChecked,
  defaultChecked,
  onCheckedChange,
  onClick,
  ...props
}: InputSwitchProps) {
  const disabled = useInputDisabled(disabledProp);
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
    // The mocks pad the track by 1px vertically and 2px horizontally; the
    // wrapper carries that so the button stays the exact track size.
    <InputTooltip tooltip={tooltip}>
      <div className="opal-switch">
        <button
          // Spread first: type/role/aria-checked/disabled/onClick are this
          // control's contract and must not be overridable through the spread.
          {...props}
          ref={ref}
          type="button"
          role="switch"
          aria-checked={checked}
          // Not the native `disabled`: callers disable the switch while a
          // change saves, and a browser drops focus from a disabled button.
          // A focused switch keeps focus; a disabled one is skipped by Tab.
          aria-disabled={disabled || undefined}
          tabIndex={disabled ? -1 : props.tabIndex}
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
      </div>
    </InputTooltip>
  );
}

export { InputSwitch, type InputSwitchProps };
