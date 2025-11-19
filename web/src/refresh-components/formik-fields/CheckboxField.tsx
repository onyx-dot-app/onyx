"use client";

import React from "react";
import { useField } from "formik";
import { cn } from "@/lib/utils";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import Checkbox from "@/refresh-components/inputs/Checkbox";

interface CheckboxFieldProps {
  name: string;
  label: string;
  labelClassName?: string;
  sublabel?: string;
  size?: "sm" | "md" | "lg";
  tooltip?: string;
  onChange?: (checked: boolean) => void;
}

export const CheckboxField: React.FC<CheckboxFieldProps> = ({
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

  const labelId = `${name}-label`;

  const checkboxContent = (
    <div className="flex w-fit items-start space-x-2">
      <Checkbox
        id={name}
        aria-labelledby={labelId}
        checked={field.value}
        onCheckedChange={(checked) => {
          helpers.setValue(Boolean(checked));
          onChange?.(Boolean(checked));
        }}
        className={cn(sizeClasses[size])}
        {...props}
      />
      <div className="flex flex-col">
        <label
          id={labelId}
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

  return (
    <SimpleTooltip tooltip={tooltip} side="top" sideOffset={25}>
      {checkboxContent}
    </SimpleTooltip>
  );
};

export default CheckboxField;
