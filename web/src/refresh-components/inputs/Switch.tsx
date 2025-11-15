"use client";

import React from "react";
import * as SwitchPrimitives from "@radix-ui/react-switch";
import { cn } from "@/lib/utils";

const rootClasses = {
  main: [
    "data-[state=checked]:bg-action-link-05",
    "data-[state=checked]:hover:bg-action-link-04",
    "data-[state=unchecked]:bg-background-tint-03",
    "data-[state=unchecked]:hover:bg-background-tint-04",
  ],
  disabled: [
    "data-[state=checked]:bg-action-link-03",
    "data-[state=unchecked]:bg-background-neutral-04",
  ],
} as const;

const thumbClasses = {
  main: ["bg-background-neutral-light-00"],
  disabled: ["bg-background-neutral-03"],
} as const;

interface SwitchProps
  extends React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root> {
  main?: boolean;
  disabled?: boolean;
}

function SwitchInner(
  { className, main, disabled, ...props }: SwitchProps,
  ref: React.ForwardedRef<React.ElementRef<typeof SwitchPrimitives.Root>>
) {
  const variant = main ? "main" : disabled ? "disabled" : "main";

  return (
    <SwitchPrimitives.Root
      ref={ref}
      className={cn(
        "peer inline-flex h-[1.125rem] w-[2rem] shrink-0 cursor-pointer items-center rounded-full transition-colors focus-visible:outline-none disabled:cursor-not-allowed",
        rootClasses[variant],
        className
      )}
      disabled={disabled}
      {...props}
    >
      <SwitchPrimitives.Thumb
        className={cn(
          "pointer-events-none block h-[0.875rem] w-[0.875rem] rounded-full ring-0 transition-transform data-[state=checked]:translate-x-[1rem] data-[state=unchecked]:translate-x-[0.125rem]",
          thumbClasses[variant]
        )}
      />
    </SwitchPrimitives.Root>
  );
}

const Switch = React.forwardRef(SwitchInner);
Switch.displayName = "Switch";
export default Switch;
