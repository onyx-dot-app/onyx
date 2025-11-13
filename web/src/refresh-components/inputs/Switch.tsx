"use client";

import * as React from "react";
import * as SwitchPrimitives from "@radix-ui/react-switch";

import { cn } from "@/lib/utils";

interface BaseSwitchProps
  extends React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root> {
  size?: "sm" | "md" | "lg";
}

function switchInner(
  { className, size = "sm", ...props }: BaseSwitchProps,
  ref: React.ForwardedRef<React.ComponentRef<typeof SwitchPrimitives.Root>>
) {
  const sizeClasses = {
    sm: "h-4 w-8",
    md: "h-5 w-10",
    lg: "h-6 w-12",
  };

  const thumbSizeClasses = {
    sm: "h-3 w-3",
    md: "h-4 w-4",
    lg: "h-5 w-5",
  };

  const translateClasses = {
    sm: "data-[state=checked]:translate-x-4",
    md: "data-[state=checked]:translate-x-5",
    lg: "data-[state=checked]:translate-x-6",
  };

  return (
    <SwitchPrimitives.Root
      ref={ref}
      className={cn(
        "peer group inline-flex shrink-0 cursor-pointer rounded-full " +
          "border-2 border-transparent transition-colors " +
          // 1) default
          "data-[state=checked]:bg-action-link-05 data-[state=unchecked]:bg-background-tint-03 " +
          // 2) hover
          "hover:data-[state=checked]:bg-action-link-04 hover:data-[state=unchecked]:bg-background-tint-04 " +
          // 3) disabled
          "disabled:cursor-not-allowed " +
          "disabled:data-[state=checked]:bg-action-link-03 disabled:data-[state=unchecked]:bg-background-neutral-04 " +
          // 4) focused
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-background-tint-04 focus-visible:ring-offset-0 " +
          // 5) focused + hover
          "data-[state=unchecked]:hover:focus-visible:border-background-tint-03 " +
          sizeClasses[size],
        className
      )}
      {...props}
    >
      <SwitchPrimitives.Thumb
        className={cn(
          "pointer-events-none block rounded-full shadow-lg ring-0 transition-transform " +
            "bg-background-neutral-00 [--background-neutral-00:var(--grey-00)] " +
            "data-[state=unchecked]:translate-x-0 " +
            "group-data-[disabled]:bg-background-neutral-03 " +
            thumbSizeClasses[size],
          translateClasses[size]
        )}
      />
    </SwitchPrimitives.Root>
  );
}

export const Switch = React.forwardRef<
  React.ComponentRef<typeof SwitchPrimitives.Root>,
  BaseSwitchProps
>(switchInner);

Switch.displayName = SwitchPrimitives.Root.displayName;
