"use client";

import * as React from "react";
import { cn, noProp } from "@/lib/utils";
import IconButton from "@/refresh-components/buttons/IconButton";
import {
  innerClasses,
  textClasses,
  Variants,
  wrapperClasses,
} from "@/refresh-components/inputs/styles";
import { SvgSearch, SvgX } from "@opal/icons";

/**
 * InputTypeIn Component
 *
 * A styled text input component with support for search icon, clear button,
 * and custom right section content.
 *
 * @example
 * ```tsx
 * // Basic usage
 * <InputTypeIn
 *   value={value}
 *   onChange={(e) => setValue(e.target.value)}
 *   placeholder="Enter text..."
 * />
 *
 * // With search icon
 * <InputTypeIn
 *   leftSearchIcon
 *   value={search}
 *   onChange={(e) => setSearch(e.target.value)}
 *   placeholder="Search..."
 * />
 *
 * // With error state
 * <InputTypeIn
 *   variant="error"
 *   value={value}
 *   onChange={(e) => setValue(e.target.value)}
 * />
 *
 * // Disabled state
 * <InputTypeIn variant="disabled" value="Cannot edit" />
 *
 * // Read-only state (non-editable, minimal styling)
 * <InputTypeIn variant="readOnly" value="Read-only value" />
 *
 * // With custom right section
 * <InputTypeIn
 *   value={password}
 *   onChange={(e) => setPassword(e.target.value)}
 *   type={showPassword ? "text" : "password"}
 *   rightSection={<IconButton icon={SvgEye} onClick={togglePassword} />}
 * />
 *
 * // Without clear button
 * <InputTypeIn
 *   showClearButton={false}
 *   value={value}
 *   onChange={(e) => setValue(e.target.value)}
 * />
 * ```
 */
export interface InputTypeInProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "disabled"> {
  variant?: Variants;

  prefixText?: string;
  leftSearchIcon?: boolean;
  rightSection?: React.ReactNode;
  showClearButton?: boolean;
  onClear?: () => void;
}
const InputTypeIn = React.forwardRef<HTMLInputElement, InputTypeInProps>(
  (
    {
      variant = "primary",
      prefixText,
      leftSearchIcon,
      rightSection,
      showClearButton = true,
      onClear,
      className,
      value,
      onChange,
      readOnly,
      ...props
    },
    ref
  ) => {
    const localInputRef = React.useRef<HTMLInputElement | null>(null);
    const disabled = variant === "disabled";
    const isReadOnlyVariant = variant === "readOnly";
    const isReadOnly = isReadOnlyVariant || readOnly;

    // Combine forwarded ref with local ref
    const setInputRef = React.useCallback(
      (node: HTMLInputElement | null) => {
        localInputRef.current = node;
        if (typeof ref === "function") {
          ref(node);
        } else if (ref) {
          (ref as React.MutableRefObject<HTMLInputElement | null>).current =
            node;
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
        className={cn(
          "flex flex-row items-center justify-between w-full h-fit p-1.5 rounded-08 relative",
          wrapperClasses[variant],
          className
        )}
        onClick={() => {
          localInputRef.current?.focus();
        }}
      >
        {leftSearchIcon && (
          <div className="pr-2">
            <div className="pl-1">
              <SvgSearch className="w-[1rem] h-[1rem] stroke-text-02" />
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
          className={cn(
            "w-full h-[1.5rem] bg-transparent p-0.5 focus:outline-none",
            innerClasses[variant],
            textClasses[variant]
          )}
          {...props}
        />

        {showClearButton && value && !disabled && !isReadOnly && (
          <IconButton
            icon={SvgX}
            disabled={disabled}
            onClick={noProp(handleClear)}
            type="button"
            internal
          />
        )}

        {rightSection}
      </div>
    );
  }
);
InputTypeIn.displayName = "InputTypeIn";

export default InputTypeIn;
