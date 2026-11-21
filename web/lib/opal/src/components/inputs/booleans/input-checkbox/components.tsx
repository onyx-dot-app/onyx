"use client";

import "@opal/components/inputs/booleans/input-checkbox/styles.css";
import React, { useEffect, useRef, useState } from "react";
import { SvgCheck, SvgMinus } from "@opal/icons";
import type { RichStr, WithoutStyles } from "@opal/types";
import {
  InputTooltip,
  useInputDisabled,
} from "@opal/components/inputs/disabled";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type CheckboxState = "unchecked" | "checked" | "indeterminate";

// ---------------------------------------------------------------------------
// InputCheckbox
// ---------------------------------------------------------------------------

/**
 * Custom checkbox built on a dual-element pattern:
 *
 * 1. Hidden `<input type="checkbox">` — form state, native validation,
 *    indeterminate property.
 * 2. Visible `<div role="checkbox">` — custom styling via `data-state` and
 *    `data-disabled` attributes, keyboard interaction.
 *
 * All visual states are driven by CSS in `styles.css`.
 *
 * Inside `InputHorizontal` or `InputVertical`, the row's `disabled` and
 * `disabledTooltip` apply to it too.
 */
type InputCheckboxProps = WithoutStyles<
  Omit<React.ComponentPropsWithoutRef<"input">, "type" | "size">
> & {
  checked?: boolean;
  defaultChecked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  indeterminate?: boolean;
  /** Shown on hover, in any state. A disabled row's reason replaces it. */
  tooltip?: string | RichStr;
  /** Ref to the hidden `<input>`. */
  ref?: React.Ref<HTMLInputElement>;
};
function InputCheckbox({
  checked: controlledChecked,
  defaultChecked,
  onCheckedChange,
  indeterminate = false,
  disabled: disabledProp,
  tooltip,
  onChange,
  id,
  name,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledby,
  "aria-describedby": ariaDescribedby,
  ref,
  ...props
}: InputCheckboxProps) {
  const disabled = useInputDisabled(disabledProp);
  const [uncontrolledChecked, setUncontrolledChecked] = useState(
    defaultChecked ?? false
  );
  const inputRef = useRef<HTMLInputElement>(null);

  // Merge refs
  useEffect(() => {
    if (ref) {
      if (typeof ref === "function") {
        ref(inputRef.current);
      } else {
        ref.current = inputRef.current;
      }
    }

    // Cleanup: clear ref on unmount
    return () => {
      if (ref) {
        if (typeof ref === "function") {
          ref(null);
        } else {
          ref.current = null;
        }
      }
    };
  }, [ref]);

  const isControlled = controlledChecked !== undefined;
  const checked = isControlled ? controlledChecked : uncontrolledChecked;

  // Set indeterminate state on the DOM element
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.indeterminate = indeterminate;
    }
  }, [indeterminate]);

  function handleChange(event: React.ChangeEvent<HTMLInputElement>) {
    if (disabled) return;

    const newChecked = event.target.checked;

    if (!isControlled) setUncontrolledChecked(newChecked);
    onChange?.(event);
    onCheckedChange?.(newChecked);
  }

  const state: CheckboxState = indeterminate
    ? "indeterminate"
    : checked
      ? "checked"
      : "unchecked";

  return (
    <InputTooltip tooltip={tooltip}>
      <div className="opal-checkbox">
        <input
          ref={inputRef}
          id={id}
          type="checkbox"
          aria-hidden="true"
          tabIndex={-1}
          className="opal-checkbox-input"
          checked={checked}
          disabled={disabled}
          onChange={handleChange}
          name={name}
          {...props}
        />
        <div
          role="checkbox"
          aria-checked={indeterminate ? "mixed" : checked}
          aria-label={ariaLabel}
          aria-labelledby={ariaLabelledby}
          aria-describedby={ariaDescribedby}
          aria-disabled={disabled || undefined}
          tabIndex={disabled ? -1 : 0}
          data-state={state}
          data-disabled={disabled || undefined}
          className="opal-checkbox-surface"
          onClick={(e) => {
            if (!disabled && inputRef.current) {
              inputRef.current.click();
              e.preventDefault();
            }
          }}
          onKeyDown={(e) => {
            if (
              !disabled &&
              inputRef.current &&
              (e.key === " " || e.key === "Enter")
            ) {
              e.preventDefault();
              inputRef.current.click();
            }
          }}
        >
          {(checked || indeterminate) && (
            <div>
              {indeterminate ? (
                <SvgMinus className="opal-checkbox-icon" />
              ) : (
                <SvgCheck className="opal-checkbox-icon" />
              )}
            </div>
          )}
        </div>
      </div>
    </InputTooltip>
  );
}

export { InputCheckbox, type InputCheckboxProps, type CheckboxState };
