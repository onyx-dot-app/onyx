"use client";

import "@opal/components/inputs/texts/input-type-in/styles.css";
import { cn } from "@opal/utils";
import { SvgSearch, SvgX } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { Button } from "@opal/components";
import { useOpalStrings } from "@opal/strings";
import type { InputVariants, WithoutStyles } from "@opal/types";

/**
 * Clears an input through the browser, so React sends its `onChange` a real
 * change event, as for typing.
 */
function clearNativeInput(input: HTMLInputElement) {
  Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value"
  )?.set?.call(input, "");
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

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
  value,
  onChange,
  name,
  ...props
}: InputTypeInProps) {
  const strings = useOpalStrings();
  const disabled = variant === "disabled";
  const isReadOnly = readOnly || variant === "readOnly";

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
              const input = event.currentTarget
                .closest(".opal-input")
                ?.querySelector("input");
              if (!input) return;
              clearNativeInput(input);
              // The button hides once the field is empty; keep focus in the
              // field rather than losing it to the page.
              input.focus();
            }}
            type="button"
            prominence="tertiary"
            size="sm"
            tooltip={strings.clear}
          />
        </div>
      )}

      {rightChildren}
    </div>
  );
}
