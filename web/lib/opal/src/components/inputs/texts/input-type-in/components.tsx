"use client";

import "@opal/components/inputs/texts/input-type-in/styles.css";
import { useCallback } from "react";
import { cn } from "@opal/utils";
import { SvgSearch, SvgX } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { Button } from "@opal/components";
import { useOpalStrings } from "@opal/strings";
import type { InputVariants, WithoutStyles } from "@opal/types";
import type { TextFont } from "@onyx-ai/shared/contracts";

/** The fonts an input can use: the body font, or mono for code-like values. */
export type InputFont = Extract<TextFont, "main-ui-body" | "main-ui-mono">;

export interface InputTypeInProps extends WithoutStyles<
  Omit<React.InputHTMLAttributes<HTMLInputElement>, "disabled" | "readOnly">
> {
  ref?: React.Ref<HTMLInputElement>;
  variant?: InputVariants;
  prefixText?: string;
  searchIcon?: boolean;
  /** Leading icon (a select's chosen option icon). Renders after `searchIcon`. */
  icon?: IconFunctionComponent;
  /** Content before the text, after `prefixText` (a chosen value shown as a tag). */
  leftChildren?: React.ReactNode;
  rightChildren?: React.ReactNode;
  /** Show the clear (×) button when the field has a value. */
  clearButton?: boolean;
  /**
   * Read-only regardless of `variant`, for a field that is only a trigger
   * (a select's button trigger). `variant="readOnly"` implies it.
   */
  readOnly?: boolean;
  /**
   * The list this field opens is open. The field keeps its focused border,
   * even when focus moves into the list.
   */
  open?: boolean;
  /** The text's font. @default "main-ui-body" */
  font?: InputFont;
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
  leftChildren,
  searchIcon,
  icon: Icon,
  rightChildren,
  clearButton = false,
  readOnly = false,
  open = false,
  font = "main-ui-body",
  value,
  onChange,
  name,
  ...props
}: InputTypeInProps) {
  const strings = useOpalStrings();
  const disabled = variant === "disabled";
  const isReadOnly = readOnly || variant === "readOnly";

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
      role="presentation"
      data-variant={variant}
      data-open={open || undefined}
      className="opal-input"
      onClick={(e) => e.currentTarget.querySelector("input")?.focus()}
    >
      {searchIcon && (
        <div className="opal-input-leading-icon">
          <SvgSearch className="opal-input-leading-icon-svg" />
        </div>
      )}

      {Icon && (
        <div className="opal-input-leading-icon">
          <Icon className="opal-input-leading-icon-svg opal-input-option-icon" />
        </div>
      )}

      {prefixText && (
        <span className="select-none pointer-events-none font-main-ui-body text-text-02 ps-0.5">
          {prefixText}
        </span>
      )}

      {leftChildren}

      <input
        ref={ref}
        type="text"
        // dir="auto": typed text decides the direction so punctuation sits on the
        // correct side. While empty it inherits the page direction (see styles.css).
        dir="auto"
        name={name}
        disabled={disabled}
        readOnly={isReadOnly}
        value={value}
        onChange={onChange}
        className="opal-input-field"
        data-font={font === "main-ui-mono" ? "mono" : undefined}
        {...props}
      />

      {clearButton && !rightChildren && !disabled && !isReadOnly && (
        <div className={cn(value === "" && "invisible")}>
          <Button
            icon={SvgX}
            aria-label={strings.clear}
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
