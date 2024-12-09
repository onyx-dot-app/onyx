import * as React from "react";

import { cn } from "@/lib/utils";

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  isEditing?: boolean;
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, isEditing = true, style, ...props }, ref) => {
    const textClassName = "text-2xl text-strong dark:text-neutral-50";
    if (!isEditing) {
      return (
        <span className={cn(textClassName, className)}>
          {props.value || props.defaultValue}
        </span>
      );
    }

    return (
      <input
        type={type}
        className={cn(
          textClassName,
          "w-[1ch] min-w-[1ch] box-content pr-1",
          className
        )}
        style={{
          width: `${Math.max(1, String(props.value || props.defaultValue || "").length)}ch`,
          ...style,
        }}
        ref={ref}
        {...props}
      />
    );
  }
);
Input.displayName = "Input";

export { Input };
