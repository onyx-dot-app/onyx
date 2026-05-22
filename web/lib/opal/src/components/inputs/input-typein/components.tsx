"use client";

import * as React from "react";
import "@opal/components/inputs/input-typein/styles.css";
import { cn } from "@opal/utils";
import { SvgSearch, SvgX } from "@opal/icons";
import { Button } from "@opal/components";
import type { InputVariants } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface InputTypeInProps extends Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  "disabled"
> {
  variant?: InputVariants;
  prefixText?: string;
  searchIcon?: boolean;
  rightChildren?: React.ReactNode;
  showClearButton?: boolean;
  onClear?: () => void;
}

// ---------------------------------------------------------------------------
// InputTypeIn
// ---------------------------------------------------------------------------

/**
 * A styled text input with support for a search icon, prefix text,
 * a clear button, and an optional right section slot.
 *
 * @example
 * ```tsx
 * // Basic
 * <InputTypeIn value={value} onChange={(e) => setValue(e.target.value)} />
 *
 * // With search icon
 * <InputTypeIn searchIcon placeholder="Search..." value={q} onChange={...} />
 *
 * // Error state
 * <InputTypeIn variant="error" value={value} onChange={...} />
 *
 * // Read-only
 * <InputTypeIn variant="readOnly" value="Cannot edit" />
 *
 * // With custom right content (e.g. password reveal)
 * <InputTypeIn
 *   value={password}
 *   onChange={...}
 *   rightChildren={<Button icon={SvgEye} onClick={toggle} />}
 * />
 * ```
 */
function InputTypeInInner(
  {
    variant = "primary",
    prefixText,
    searchIcon,
    rightChildren,
    showClearButton = true,
    onClear,
    className,
    value,
    onChange,
    readOnly,
    ...props
  }: InputTypeInProps,
  ref: React.ForwardedRef<HTMLInputElement>
) {
  const localInputRef = React.useRef<HTMLInputElement | null>(null);
  const disabled = variant === "disabled";
  const isReadOnly = variant === "readOnly" || readOnly;

  const setInputRef = React.useCallback(
    (node: HTMLInputElement | null) => {
      localInputRef.current = node;
      if (typeof ref === "function") {
        ref(node);
      } else if (ref) {
        (ref as React.MutableRefObject<HTMLInputElement | null>).current = node;
      }
    },
    [ref]
  );

  const handleClear = React.useCallback(() => {
    if (onClear) {
      onClear();
      return;
    }
    onChange?.({
      target: { value: "" },
      currentTarget: { value: "" },
      type: "change",
      bubbles: true,
      cancelable: true,
    } as React.ChangeEvent<HTMLInputElement>);
  }, [onClear, onChange]);

  return (
    <div
      data-variant={variant}
      className={cn("opal-input", className)}
      onClick={() => localInputRef.current?.focus()}
    >
      {searchIcon && (
        <div className="pr-2 pl-1">
          <div className="pl-1">
            <SvgSearch className="w-4 h-4 stroke-text-02" />
          </div>
        </div>
      )}

      {prefixText && (
        <span className="select-none pointer-events-none text-text-02 pl-0.5">
          {prefixText}
        </span>
      )}

      <input
        ref={setInputRef}
        type="text"
        disabled={disabled}
        readOnly={isReadOnly}
        value={value}
        onChange={onChange}
        className="opal-input-field"
        {...props}
      />

      {showClearButton && !disabled && !isReadOnly && (
        <div className={cn(!value && "invisible")}>
          <Button
            icon={SvgX}
            disabled={disabled}
            onClick={(event) => {
              event.stopPropagation();
              handleClear();
            }}
            type="button"
            prominence="internal"
          />
        </div>
      )}

      {rightChildren}
    </div>
  );
}

const InputTypeIn = React.forwardRef(InputTypeInInner);
InputTypeIn.displayName = "InputTypeIn";
export { InputTypeIn };
export default InputTypeIn;
