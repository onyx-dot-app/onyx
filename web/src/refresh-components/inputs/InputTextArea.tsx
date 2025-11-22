"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { divClasses, innerClasses } from "./InputTypeIn";

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

function InputTextAreaInner(
  {
    main,
    internal,
    error,
    disabled,
    className,
    rows = 4,
    ...props
  }: InputTextAreaProps,
  ref: React.ForwardedRef<HTMLTextAreaElement>
) {
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
        divClasses[variant],
        "flex flex-row items-start justify-between w-full h-fit p-1.5 rounded-08 bg-background-neutral-00 relative",
        className
      )}
    >
      <textarea
        ref={ref}
        disabled={disabled}
        className={cn(
          innerClasses[variant],
          "w-full min-h-[3rem] bg-transparent p-0.5 focus:outline-none resize-y"
        )}
        rows={rows}
        {...props}
      />
    </div>
  );
}

const InputTextArea = React.forwardRef(InputTextAreaInner);
InputTextArea.displayName = "InputTextArea";
export default InputTextArea;
