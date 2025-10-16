"use client";

import React from "react";
import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import { Check } from "lucide-react";
import { useField } from "formik";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import Text from "@/refresh-components/texts/Text";

interface CheckFieldProps {
  name: string;
  label: string;
  labelClassName?: string;
  sublabel?: string;
  size?: "sm" | "md" | "lg";
  tooltip?: string;
  onChange?: (checked: boolean) => void;
}

export const CheckFormField: React.FC<CheckFieldProps> = ({
  name,
  label,
  onChange,
  sublabel,
  size = "md",
  tooltip,
  labelClassName,
  ...props
}) => {
  const [field, , helpers] = useField<boolean>({ name, type: "checkbox" });

  const sizeClasses = {
    sm: "h-2 w-2",
    md: "h-3 w-3",
    lg: "h-4 w-4",
  };

  const handleClick = (e: React.MouseEvent<HTMLLabelElement>) => {
    e.preventDefault();
    const next = !field.value;
    helpers.setValue(next);
    onChange?.(next);
  };

  const checkboxContent = (
    <div className="flex w-fit items-start space-x-2">
      <CheckboxPrimitive.Root
        id={name}
        checked={field.value}
        onCheckedChange={(checked) => {
          helpers.setValue(Boolean(checked));
          onChange?.(Boolean(checked));
        }}
        className={cn(
          "peer shrink-0 rounded-sm border border-background-200 bg-white ring-offset-white " +
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-950 " +
            "focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 " +
            "data-[state=checked]:bg-neutral-900 data-[state=checked]:text-neutral-50 " +
            "dark:border-background-800 dark:ring-offset-neutral-950 dark:focus-visible:ring-neutral-300 " +
            "dark:data-[state=checked]:bg-neutral-50 dark:data-[state=checked]:text-neutral-900",
          sizeClasses[size]
        )}
        {...props}
      >
        <CheckboxPrimitive.Indicator className="flex items-center justify-center text-current">
          <Check className={sizeClasses[size]} />
        </CheckboxPrimitive.Indicator>
      </CheckboxPrimitive.Root>
      <div className="flex flex-col">
        <label
          htmlFor={name}
          className="flex flex-col cursor-pointer"
          onClick={handleClick}
        >
          <span
            className={cn(
              "text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70",
              labelClassName
            )}
          >
            {label}
          </span>
          {sublabel && (
            <span className="text-sm text-muted-foreground mt-1">
              {sublabel}
            </span>
          )}
        </label>
      </div>
    </div>
  );

  return tooltip ? (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>{checkboxContent}</TooltipTrigger>
        <TooltipContent side="top" align="center" sideOffset={25}>
          <Text inverted>{tooltip}</Text>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  ) : (
    checkboxContent
  );
};
