"use client";

import * as React from "react";
import { cn, mergeRefs } from "@/lib/utils";
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
  autoResize?: boolean;
  maxRows?: number;
}
const InputTextArea = React.forwardRef<HTMLTextAreaElement, InputTextAreaProps>(
  (
    {
      variant = "primary",
      className,
      rows = 4,
      readOnly,
      autoResize = false,
      maxRows,
      ...props
    },
    ref
  ) => {
    const disabled = variant === "disabled";
    const isReadOnlyVariant = variant === "readOnly";
    const isReadOnly = isReadOnlyVariant || readOnly;

    const internalRef = React.useRef<HTMLTextAreaElement | null>(null);
    const cachedLineHeight = React.useRef<number | null>(null);

    const adjustHeight = React.useCallback(() => {
      const textarea = internalRef.current;
      if (!textarea || !autoResize) return;

      if (cachedLineHeight.current === null) {
        cachedLineHeight.current =
          parseFloat(getComputedStyle(textarea).lineHeight) || 20;
      }
      const lineHeight = cachedLineHeight.current;

      // Reset to auto so scrollHeight reflects actual content
      textarea.style.height = "auto";
      textarea.style.overflowY = "hidden";

      const minHeight = rows * lineHeight;
      const maxHeight = maxRows ? maxRows * lineHeight : Infinity;

      const contentHeight = textarea.scrollHeight;
      const clampedHeight = Math.min(
        Math.max(contentHeight, minHeight),
        maxHeight
      );

      textarea.style.height = `${clampedHeight}px`;
      textarea.style.overflowY = contentHeight > maxHeight ? "auto" : "hidden";
    }, [autoResize, rows, maxRows]);

    React.useEffect(() => {
      adjustHeight();
    }, [adjustHeight, props.value]);

    const resizeClass = autoResize ? "resize-none" : "resize-y";

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
          ref={mergeRefs(internalRef, ref)}
          disabled={disabled}
          readOnly={isReadOnly}
          className={cn(
            "w-full min-h-[3rem] bg-transparent focus:outline-none p-0.5",
            resizeClass,
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
