"use client";

import React, { useState } from "react";
import { cn } from "@/lib/utils";

export interface SwitchProps
  extends Omit<React.ComponentPropsWithoutRef<"button">, "onChange"> {
  // Switch variants
  disabled?: boolean;

  checked?: boolean;
  defaultChecked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
}
const Switch = React.forwardRef<HTMLButtonElement, SwitchProps>(
  (
    {
      disabled,

      checked: controlledChecked,
      defaultChecked,
      onCheckedChange,

      className,
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
        data-state={checked ? "checked" : "unchecked"}
        className={cn(
          "peer inline-flex h-[1.125rem] w-[2rem] shrink-0 cursor-pointer items-center rounded-full transition-colors focus-visible:outline-none",
          disabled ? "switch-disabled" : "switch-normal",
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
            disabled ? "switch-thumb-disabled" : "switch-thumb"
          )}
        />
      </button>
    );
  }
);
Switch.displayName = "Switch";

export default Switch;
