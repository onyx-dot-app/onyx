"use client";

import { InputContainer } from "@opal/components/inputs/container";
// The field reuses InputTypeIn's .opal-input-field base, color, and placeholder rules.
import "@opal/components/inputs/texts/input-type-in/styles.css";
import "@opal/components/inputs/texts/input-text-area/styles.css";
import React from "react";
import type { InputVariants, RichStr, WithoutStyles } from "@opal/types";
import { cn, mergeRefs } from "@opal/utils";
import {
  InputTooltip,
  useInputDisabled,
} from "@opal/components/inputs/disabled";

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

  /** Shown on hover, in any state. A disabled row's reason replaces it. */
  tooltip?: string | RichStr;

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

  /** Monospace text, for code or queries. */
  mono?: boolean;

  ref?: React.Ref<HTMLTextAreaElement>;
}

// ---------------------------------------------------------------------------
// InputTextArea
// ---------------------------------------------------------------------------

/**
 * Multiline text field on the `.opal-input` chrome.
 *
 * Inside `InputHorizontal` or `InputVertical`, the row's `disabled` sets the
 * `"disabled"` variant and its `disabledTooltip` applies too.
 */
function InputTextArea({
  variant: variantProp = "primary",
  tooltip,
  rows = 4,
  autoResize = false,
  maxRows,
  resizable = true,
  rightSection,
  mono = false,
  ref,
  ...props
}: InputTextAreaProps) {
  const variant: InputVariants = useInputDisabled(false)
    ? "disabled"
    : variantProp;
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
    <InputTooltip tooltip={tooltip}>
      <InputContainer className="opal-input-textarea" variant={variant} grows>
        {/* raw-ok: Opal ships no textarea element, this component IS the library's textarea */}
        <textarea
          ref={mergeRefs(internalRef, ref)}
          dir="auto"
          disabled={disabled}
          readOnly={isReadOnly}
          className={cn(
            "opal-input-field opal-input-textarea-field",
            autoResize || !resizable ? "resize-none" : "resize-y"
          )}
          data-mono={mono || undefined}
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
      </InputContainer>
    </InputTooltip>
  );
}

export { InputTextArea, type InputTextAreaProps };
