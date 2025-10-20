"use client";

import React from "react";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";

interface FieldInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string;
  description?: string;
  placeholder: string;
}

function FieldInputInner(
  { label, description, placeholder, className, ...props }: FieldInputProps,
  ref: React.ForwardedRef<HTMLInputElement>
) {
  return (
    <div className="flex flex-col gap-spacing-interline w-full">
      <Text mainUiAction>{label}</Text>
      <input
        ref={ref}
        type="text"
        placeholder={placeholder}
        autoFocus
        className={cn(
          "w-full p-spacing-interline rounded-08 border bg-background-neutral-00",
          "text-text-05 placeholder:font-secondary-body placeholder:text-text-02",
          "focus:outline-none focus:ring-0 focus:border-theme-primary-05",
          className
        )}
        {...props}
      />
      {description && <Text text03>{description}</Text>}
    </div>
  );
}

const FieldInput = React.forwardRef(FieldInputInner);
FieldInput.displayName = "FieldInput";

export default FieldInput;
