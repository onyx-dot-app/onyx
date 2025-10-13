"use client";

import * as React from "react";
import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import { Check } from "lucide-react";
import { useField } from "formik";
import { cn } from "@/lib/utils";

interface BaseCheckboxProps
  extends React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root> {
  size?: "sm" | "md" | "lg";
}

export const Checkbox = React.forwardRef<
  React.ElementRef<typeof CheckboxPrimitive.Root>,
  BaseCheckboxProps
>(({ className, size = "md", ...props }, ref) => {
  const sizeClasses = {
    sm: "h-3 w-3",
    md: "h-4 w-4",
    lg: "h-5 w-5",
  };

  return (
    <CheckboxPrimitive.Root
      ref={ref}
      className={cn(
        "rounded-04 border border-border-02",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "bg-background-neutral-02",
        sizeClasses[size],
        className
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator className="flex items-center justify-center text-current">
        <Check className={sizeClasses[size]} />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
});

Checkbox.displayName = "Checkbox";

interface CheckboxFieldProps extends Omit<BaseCheckboxProps, "checked"> {
  name: string;
}

export const CheckboxField: React.FC<CheckboxFieldProps> = ({
  name,
  ...props
}) => {
  const [field, , helpers] = useField<boolean>({ name, type: "checkbox" });

  return (
    <Checkbox
      checked={field.value}
      onCheckedChange={(checked) => {
        helpers.setValue(Boolean(checked));
      }}
      {...props}
    />
  );
};
