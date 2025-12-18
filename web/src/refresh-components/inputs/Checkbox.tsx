"use client";

import React, { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { SvgCheck, SvgMinus } from "@opal/icons";
const getRootClasses = (checked: boolean, indeterminate: boolean) => ({
  main:
    checked || indeterminate
      ? [
          "bg-action-link-05",
          "hover:bg-action-link-04",
          "focus-visible:border-border-05",
          "focus-visible:focus-shadow",
        ]
      : [
          "bg-background-neutral-00",
          "border",
          "border-border-02",
          "hover:border-border-03",
          "focus-visible:border-border-05",
          "focus-visible:focus-shadow",
        ],
  disabled:
    checked || indeterminate
      ? ["bg-background-neutral-04"]
      : ["bg-background-neutral-03", "border", "border-border-02"],
});

export interface CheckboxProps extends Omit<
  React.ComponentPropsWithoutRef<"input">,
  "type" | "size"
> {
  checked?: boolean;
  defaultChecked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  indeterminate?: boolean;
}

function CheckboxInner(
  {
    checked: controlledChecked,
    defaultChecked,
    onCheckedChange,
    indeterminate = false,
    disabled,
    className,
    onChange,
    id,
    name,
    "aria-label": ariaLabel,
    "aria-labelledby": ariaLabelledby,
    "aria-describedby": ariaDescribedby,
    ...props
  }: CheckboxProps,
  ref: React.ForwardedRef<HTMLInputElement>
) {
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

  const variant = disabled ? "disabled" : "main";
  const rootClasses = getRootClasses(checked, indeterminate);

  return (
    <div className="relative inline-flex shrink-0">
      {/*
        Dual-element pattern for custom checkbox:
        1. Hidden input: Maintains form state, enables form submission, supports indeterminate property
        2. Visible div: Provides custom styling, handles user interaction, accessible via role="checkbox"
        The div's click handler triggers the input's native click, preserving standard checkbox behavior.
      */}
      <input
        ref={inputRef}
        type="checkbox"
        role="presentation"
        className="sr-only peer"
        checked={checked}
        disabled={disabled}
        onChange={handleChange}
        name={name}
        {...props}
      />
      <div
        id={id}
        role="checkbox"
        aria-checked={indeterminate ? "mixed" : checked}
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledby}
        aria-describedby={ariaDescribedby}
        tabIndex={disabled ? -1 : 0}
        className={cn(
          "flex h-4 w-4 shrink-0 items-center justify-center rounded-04 transition-colors",
          disabled ? "cursor-not-allowed" : "cursor-pointer",
          rootClasses[variant],
          className
        )}
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
              <SvgMinus className="h-3 w-3 stroke-text-light-05" />
            ) : (
              <SvgCheck className="h-3 w-3 stroke-text-light-05" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

const Checkbox = React.forwardRef(CheckboxInner);
Checkbox.displayName = "Checkbox";
export default Checkbox;
