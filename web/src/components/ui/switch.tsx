"use client";

import * as React from "react";
import * as SwitchPrimitives from "@radix-ui/react-switch";
import { useField } from "formik";

import { cn } from "@/lib/utils";

interface BaseSwitchProps
  extends React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root> {
  circleClassName?: string;
  size?: "sm" | "md" | "lg";
}

export const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitives.Root>,
  BaseSwitchProps
>(({ circleClassName, className, size = "md", ...props }, ref) => {
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
        "peer inline-flex shrink-0 cursor-pointer items-center rounded-full " +
          "border-2 border-transparent transition-colors focus-visible:outline-none " +
          "focus-visible:ring-2 focus-visible:ring-neutral-950 focus-visible:ring-offset-2 " +
          "focus-visible:ring-offset-white disabled:cursor-not-allowed disabled:opacity-50 " +
          "data-[state=checked]:bg-neutral-900 data-[state=unchecked]:bg-neutral-200 " +
          "dark:focus-visible:ring-neutral-300 dark:focus-visible:ring-offset-neutral-950 " +
          "dark:data-[state=checked]:bg-neutral-200 dark:data-[state=unchecked]:bg-neutral-700 " +
          sizeClasses[size],
        className
      )}
      {...props}
    >
      <SwitchPrimitives.Thumb
        className={cn(
          "pointer-events-none block rounded-full bg-white shadow-lg ring-0 transition-transform " +
            "data-[state=unchecked]:translate-x-0 dark:bg-neutral-950",
          thumbSizeClasses[size],
          translateClasses[size],
          circleClassName
        )}
      />
    </SwitchPrimitives.Root>
  );
});

Switch.displayName = SwitchPrimitives.Root.displayName;

interface SwitchFieldProps extends Omit<BaseSwitchProps, "checked"> {
  name: string;
}

export const SwitchField: React.FC<SwitchFieldProps> = ({
  name,
  onCheckedChange,
  ...props
}) => {
  const [field, , helpers] = useField<boolean>({ name, type: "checkbox" });

  return (
    <Switch
      checked={field.value}
      onCheckedChange={(checked) => {
        helpers.setValue(Boolean(checked));
        onCheckedChange?.(checked);
      }}
      {...props}
    />
  );
};
