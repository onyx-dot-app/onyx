"use client";

import React, { useState } from "react";
import { cn } from "@/lib/utils";

const rootClasses = (checked?: boolean) =>
  ({
    main: checked
      ? ["bg-action-link-05", "hover:bg-action-link-04"]
      : ["bg-background-tint-03", "hover:bg-background-tint-04"],
    disabled: checked ? ["bg-action-link-03"] : ["bg-background-neutral-04"],
  }) as const;

const thumbClasses = {
  main: ["bg-background-neutral-light-00"],
  disabled: ["bg-background-neutral-03"],
} as const;

export interface SwitchProps
  extends Omit<React.ComponentPropsWithoutRef<"button">, "onChange"> {
  // Switch variants
  disabled?: boolean;

  checked?: boolean;
  defaultChecked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
}

function SwitchInner(
  {
    disabled,

    checked: controlledChecked,
    defaultChecked,
    onCheckedChange,

    className,
    onClick,
    ...props
  }: SwitchProps,
  ref: React.ForwardedRef<HTMLButtonElement>
) {
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

  const variant = disabled ? "disabled" : "main";

  return (
    <button
      ref={ref}
      type="button"
      role="switch"
      aria-checked={checked}
      data-state={checked ? "checked" : "unchecked"}
      className={cn(
        "peer inline-flex h-[1.125rem] w-[2rem] shrink-0 cursor-pointer items-center rounded-full transition-colors focus-visible:outline-none disabled:cursor-not-allowed",
        rootClasses(checked)[variant],
        "border border-transparent",
        "focus-within:focus-shadow focus-within:hover:!border-border-01",
        className
      )}
      disabled={disabled}
      onClick={handleClick}
      {...props}
    >
      <span
        data-state={checked ? "checked" : "unchecked"}
        className={cn(
          "pointer-events-none block h-[0.875rem] w-[0.875rem] rounded-full ring-0 transition-transform data-[state=checked]:translate-x-[15px] data-[state=unchecked]:translate-x-[1px]",
          thumbClasses[variant]
        )}
      />
    </button>
  );
}

const Switch = React.forwardRef(SwitchInner);
Switch.displayName = "Switch";
export default Switch;
