"use client";

import React, { useEffect, useRef, useState } from "react";
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

export interface InputTextAreaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  // Input states:
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
  const localRef = useRef<HTMLTextAreaElement>(null);

  // Use forwarded ref if provided, otherwise use local ref
  const textareaRef = ref || localRef;

  const state = main
    ? "main"
    : internal
      ? "internal"
      : error
        ? "error"
        : disabled
          ? "disabled"
          : "main";

  useEffect(() => {
    // if disabled, set cursor to "not-allowed"
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
        divClasses[state],
        className
      )}
      onClick={() => {
        if (
          hovered &&
          textareaRef &&
          typeof textareaRef === "object" &&
          textareaRef.current
        ) {
          textareaRef.current.focus();
        }
      }}
    >
      <textarea
        ref={textareaRef}
        disabled={disabled}
        className={cn(
          "w-full min-h-[3rem] bg-transparent p-0.5 focus:outline-none resize-y",
          textareaClasses[state]
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
