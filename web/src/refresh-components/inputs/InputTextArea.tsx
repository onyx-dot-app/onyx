"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { useBoundingBox } from "@/hooks/useBoundingBox";

const divClasses = {
  main: [
    "border",
    "hover:border-border-02",
    "active:!border-border-05",
    "focus-within:!border-border-05",
  ],
  internal: [],
  error: ["border", "border-status-error-05"],
  disabled: ["bg-background-neutral-03"],
} as const;

const textareaClasses = {
  main: [
    "text-text-04 placeholder:!font-secondary-body placeholder:text-text-02",
  ],
  internal: [],
  error: [],
  disabled: ["text-text-02"],
} as const;

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
  const { ref: boundingBoxRef, inside: hovered } = useBoundingBox();
  const localRef = React.useRef<HTMLTextAreaElement>(null);

  // Combine forwarded ref with local ref
  const textareaRef = React.useCallback(
    (node: HTMLTextAreaElement | null) => {
      localRef.current = node;
      if (typeof ref === "function") {
        ref(node);
      } else if (ref) {
        (ref as React.MutableRefObject<HTMLTextAreaElement | null>).current =
          node;
      }
    },
    [ref]
  );

  const variant = main
    ? "main"
    : internal
      ? "internal"
      : error
        ? "error"
        : disabled
          ? "disabled"
          : "main";

  // Set cursor style based on disabled state and hover
  React.useEffect(() => {
    if (disabled && hovered) {
      document.body.style.cursor = "not-allowed";
    } else if (!disabled && hovered) {
      document.body.style.cursor = "text";
    } else {
      document.body.style.cursor = "default";
    }
  }, [disabled, hovered]);

  return (
    <div
      ref={boundingBoxRef}
      className={cn(
        "flex flex-row items-start justify-between w-full h-fit p-1.5 rounded-08 bg-background-neutral-00 relative",
        divClasses[variant],
        className
      )}
      onClick={() => {
        if (hovered && localRef.current) {
          localRef.current.focus();
        }
      }}
    >
      <textarea
        ref={textareaRef}
        disabled={disabled}
        className={cn(
          "w-full min-h-[3rem] bg-transparent p-0.5 focus:outline-none resize-y",
          textareaClasses[variant]
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
