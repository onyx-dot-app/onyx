"use client";

import "@opal/components/inputs/shared.css";
// The field reuses InputTypeIn's .opal-input-field base, color, and placeholder rules.
import "@opal/components/inputs/input-type-in/styles.css";
import "@opal/components/inputs/input-text-area/styles.css";
import React from "react";
import type { InputVariants, WithoutStyles } from "@opal/types";
import { cn, mergeRefs } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface InputTextAreaProps extends WithoutStyles<
  Omit<
    React.TextareaHTMLAttributes<HTMLTextAreaElement>,
    "disabled" | "readOnly"
  >
> {
  variant?: InputVariants;

  /**
   * Grow with content between `rows` and `maxRows`. Disables manual
   * resizing.
   */
  autoResize?: boolean;

  /** Row cap for `autoResize`. Content beyond it scrolls. */
  maxRows?: number;

  /** Allow manual vertical resizing. Ignored when `autoResize` is set. */
  resizable?: boolean;

  /** Slot pinned to the top-right inside the field. */
  rightSection?: React.ReactNode;

  ref?: React.Ref<HTMLTextAreaElement>;
}

// ---------------------------------------------------------------------------
// InputTextArea
// ---------------------------------------------------------------------------

/** Multiline text field on the `.opal-input` chrome. */
function InputTextArea({
  variant = "primary",
  rows = 4,
  autoResize = false,
  maxRows,
  resizable = true,
  rightSection,
  ref,
  ...props
}: InputTextAreaProps) {
  const disabled = variant === "disabled";
  const isReadOnly = variant === "readOnly";

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

    // Reset to auto so scrollHeight reflects the actual content.
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

  return (
    <div className="opal-input opal-input-textarea" data-variant={variant}>
      {/* raw-ok: Opal ships no textarea element, this component IS the library's textarea */}
      <textarea
        ref={mergeRefs(internalRef, ref)}
        disabled={disabled}
        readOnly={isReadOnly}
        className={cn(
          "opal-input-field opal-input-textarea-field",
          autoResize || !resizable ? "resize-none" : "resize-y"
        )}
        rows={rows}
        {...props}
        // After the spread so uncontrolled typing also resizes. The effect
        // covers programmatic value changes.
        onInput={(event) => {
          adjustHeight();
          props.onInput?.(event);
        }}
      />
      {rightSection && (
        <div className="opal-input-textarea-right">{rightSection}</div>
      )}
    </div>
  );
}

export { InputTextArea, type InputTextAreaProps };
