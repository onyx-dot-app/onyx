"use client";

import * as React from "react";
import { cn, noProp } from "@/lib/utils";
import SvgX from "@/icons/x";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgSearch from "@/icons/search";
import {
  innerClasses,
  wrapperClasses,
} from "@/refresh-components/inputs/styles";

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
 *   error
 *   value={value}
 *   onChange={(e) => setValue(e.target.value)}
 * />
 *
 * // Disabled state
 * <InputTypeIn disabled value="Cannot edit" />
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
  extends React.InputHTMLAttributes<HTMLInputElement> {
  // input-type-in variants
  internal?: boolean;
  error?: boolean;
  disabled?: boolean;

  leftSearchIcon?: boolean;
  rightSection?: React.ReactNode;
  showClearButton?: boolean;
  onClear?: () => void;
}

function InputTypeInInner(
  {
    internal,
    error,
    disabled,
    leftSearchIcon,
    rightSection,
    showClearButton = true,
    onClear,
    className,
    value,
    onChange,
    ...props
  }: InputTypeInProps,
  ref: React.ForwardedRef<HTMLInputElement>
) {
  const localInputRef = React.useRef<HTMLInputElement | null>(null);

  // Combine forwarded ref with local ref
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

  const variant = internal
    ? "internal"
    : error
      ? "error"
      : disabled
        ? "disabled"
        : "main";

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

      <input
        ref={setInputRef}
        type="text"
        disabled={disabled}
        value={value}
        onChange={onChange}
        className={cn(
          "w-full h-[1.5rem] bg-transparent p-0.5 focus:outline-none",
          innerClasses[variant]
        )}
        {...props}
      />

      {showClearButton && value && (
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

const InputTypeIn = React.forwardRef(InputTypeInInner);
InputTypeIn.displayName = "InputTypeIn";
export default InputTypeIn;
