"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import {
  innerClasses,
  textClasses,
  Variants,
  wrapperClasses,
} from "@/refresh-components/inputs/styles";

/**
 * InputTextArea Component
 *
 * A styled textarea component with support for various states and auto-resize.
 *
 * @example
 * ```tsx
 * // Basic usage
 * <InputTextArea
 *   value={value}
 *   onChange={(e) => setValue(e.target.value)}
 *   placeholder="Enter description..."
 * />
 *
 * // With error state
 * <InputTextArea
 *   variant="error"
 *   value={value}
 *   onChange={(e) => setValue(e.target.value)}
 * />
 *
 * // Disabled state
 * <InputTextArea variant="disabled" value="Cannot edit" />
 *
 * // Read-only state (non-editable, minimal styling)
 * <InputTextArea variant="readOnly" value="Read-only value" />
 *
 * // Custom rows
 * <InputTextArea
 *   rows={8}
 *   value={value}
 *   onChange={(e) => setValue(e.target.value)}
 * />
 *
 * // Internal styling (no border)
 * <InputTextArea variant="internal" value={value} onChange={handleChange} />
 * ```
 */
export interface InputTextAreaProps
  extends Omit<React.TextareaHTMLAttributes<HTMLTextAreaElement>, "disabled"> {
  variant?: Variants;
}
const InputTextArea = React.forwardRef<HTMLTextAreaElement, InputTextAreaProps>(
  ({ variant = "primary", className, rows = 4, readOnly, ...props }, ref) => {
    const disabled = variant === "disabled";
    const isReadOnlyVariant = variant === "readOnly";
    const isReadOnly = isReadOnlyVariant || readOnly;

    return (
      <div
        className={cn(
          wrapperClasses[variant],
          "flex flex-row items-start justify-between w-full h-fit p-1.5 rounded-08 relative",
          !isReadOnlyVariant && "bg-background-neutral-00",
          className
        )}
      >
        <textarea
          ref={ref}
          disabled={disabled}
          readOnly={isReadOnly}
          className={cn(
            "w-full min-h-[3rem] bg-transparent focus:outline-none resize-y p-0.5",
            innerClasses[variant],
            textClasses[variant]
          )}
          rows={rows}
          {...props}
        />
      </div>
    );
  }
);
InputTextArea.displayName = "InputTextArea";

export default InputTextArea;
