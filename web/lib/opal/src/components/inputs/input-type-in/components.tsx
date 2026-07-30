"use client";

import "@opal/components/inputs/input-type-in/styles.css";
import { useCallback } from "react";
import { cn } from "@opal/utils";
import { SvgSearch, SvgX } from "@opal/icons";
import { Button } from "@opal/components";
import type { InputVariants, WithoutStyles } from "@opal/types";

export interface InputTypeInProps extends WithoutStyles<
  Omit<React.InputHTMLAttributes<HTMLInputElement>, "disabled" | "readOnly">
> {
  ref?: React.Ref<HTMLInputElement>;
  variant?: InputVariants;
  prefixText?: string;
  searchIcon?: boolean;
  rightChildren?: React.ReactNode;
  /** Show the clear (×) button when the field has a value. */
  clearButton?: boolean;
}

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
 * // With clear button
 * <InputTypeIn clearButton value={q} onChange={...} />
 *
 * // With custom right content (e.g. password reveal) — suppresses clear button
 * <InputTypeIn
 *   value={password}
 *   onChange={...}
 *   rightChildren={<Button icon={SvgEye} onClick={toggle} />}
 * />
 * ```
 */
export default function InputTypeIn({
  ref,
  variant = "primary",
  prefixText,
  searchIcon,
  rightChildren,
  clearButton = false,
  value,
  onChange,
  name,
  ...props
}: InputTypeInProps) {
  const disabled = variant === "disabled";
  const isReadOnly = variant === "readOnly";

  const handleClear = useCallback(() => {
    onChange?.({
      target: { value: "", name: name ?? "" },
      currentTarget: { value: "", name: name ?? "" },
      type: "change",
      bubbles: true,
      cancelable: true,
    } as React.ChangeEvent<HTMLInputElement>);
  }, [onChange, name]);

  return (
    <div
      data-variant={variant}
      className="opal-input"
      onClick={(e) => e.currentTarget.querySelector("input")?.focus()}
    >
      {searchIcon && (
        <div className="px-1">
          <SvgSearch className="w-4 h-4 stroke-text-02" />
        </div>
      )}

      {prefixText && (
        <span className="select-none pointer-events-none text-text-02 pl-0.5">
          {prefixText}
        </span>
      )}

      <input
        ref={ref}
        type="text"
        name={name}
        disabled={disabled}
        readOnly={isReadOnly}
        value={value}
        onChange={onChange}
        className="opal-input-field"
        {...props}
      />

      {clearButton && !rightChildren && !disabled && !isReadOnly && (
        <div className={cn(value === "" && "invisible")}>
          <Button
            icon={SvgX}
            disabled={disabled}
            onClick={(event) => {
              event.stopPropagation();
              handleClear();
            }}
            type="button"
            prominence="internal"
            size="sm"
          />
        </div>
      )}

      {rightChildren}
    </div>
  );
}
