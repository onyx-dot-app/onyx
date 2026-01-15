"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import {
  wrapperClasses,
  innerClasses,
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
 *   error
 *   value={value}
 *   onChange={(e) => setValue(e.target.value)}
 * />
 *
 * // Disabled state
 * <InputTextArea disabled value="Cannot edit" />
 *
 * // Custom rows
 * <InputTextArea
 *   rows={8}
 *   value={value}
 *   onChange={(e) => setValue(e.target.value)}
 * />
 *
 * // Internal styling (no border)
 * <InputTextArea internal value={value} onChange={handleChange} />
 * ```
 */
export interface InputTextAreaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  // input-text-area variants
  main?: boolean;
  internal?: boolean;
  error?: boolean;
  disabled?: boolean;
}
const InputTextArea = React.forwardRef<HTMLTextAreaElement, InputTextAreaProps>(
  ({ main, internal, error, disabled, className, rows = 4, ...props }, ref) => {
    const variant = main
      ? "main"
      : internal
        ? "internal"
        : error
          ? "error"
          : disabled
            ? "disabled"
            : "main";

    return (
      <div
        className={cn(
          wrapperClasses[variant],
          "flex flex-row items-start justify-between w-full h-fit p-1.5 rounded-08 bg-background-neutral-00 relative",
          className
        )}
      >
        <textarea
          ref={ref}
          disabled={disabled}
          className={cn(
            innerClasses[variant],
            "w-full min-h-[3rem] bg-transparent focus:outline-none resize-y p-0.5"
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
