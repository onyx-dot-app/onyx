"use client";

import * as React from "react";
import InputTypeIn, {
  InputTypeInProps,
} from "@/refresh-components/inputs/InputTypeIn";
import IconButton from "@/refresh-components/buttons/IconButton";
import { noProp } from "@/lib/utils";
import { SvgEye, SvgEyeClosed } from "@opal/icons";

// ASTERISK OPERATOR (U+2217) - better sized than bullet (•)
const MASK_CHARACTER = "∗";

// Backend placeholder pattern - indicates a stored value that can't be revealed
const BACKEND_PLACEHOLDER_PATTERN = /^•+$/; // All bullet characters (U+2022)

/**
 * Check if a value is a backend placeholder (all bullet characters).
 * The backend sends this to indicate a stored secret exists without revealing it.
 */
function isBackendPlaceholder(value: string): boolean {
  return !!value && BACKEND_PLACEHOLDER_PATTERN.test(value);
}

export interface PasswordInputTypeInProps
  extends Omit<InputTypeInProps, "type" | "rightSection" | "leftSearchIcon"> {
  /**
   * When true, the reveal toggle is disabled.
   * Use this when displaying a stored/masked value from the backend
   * that cannot actually be revealed.
   * The input remains editable so users can type a new value.
   */
  isNonRevealable?: boolean;
}

/**
 * PasswordInputTypeIn Component
 *
 * A password input with custom mask character (∗) and reveal/hide toggle.
 * Built on top of InputTypeIn for consistency.
 *
 * Features:
 * - Custom mask character (∗) instead of browser default
 * - Show/hide toggle button only visible when input has value or is focused
 * - When revealed, the toggle icon uses action style (more prominent)
 * - When hidden, the toggle icon uses internal style (muted)
 * - Optional `isNonRevealable` prop to disable reveal (for stored backend values)
 */
const PasswordInputTypeIn = React.forwardRef<
  HTMLInputElement,
  PasswordInputTypeInProps
>(function PasswordInputTypeIn(
  {
    isNonRevealable = false,
    value,
    onChange,
    onFocus,
    onBlur,
    disabled,
    showClearButton = false,
    ...props
  },
  ref
) {
  const [isPasswordVisible, setIsPasswordVisible] = React.useState(false);
  const [isFocused, setIsFocused] = React.useState(false);

  const realValue = String(value || "");
  const hasValue = realValue.length > 0;
  const effectiveNonRevealable =
    isNonRevealable || isBackendPlaceholder(realValue);
  const isHidden = !isPasswordVisible || effectiveNonRevealable;

  const getDisplayValue = (): string => {
    if (isHidden) {
      return MASK_CHARACTER.repeat(realValue.length);
    }
    return realValue;
  };

  const handleFocus = React.useCallback(
    (e: React.FocusEvent<HTMLInputElement>) => {
      setIsFocused(true);
      onFocus?.(e);
    },
    [onFocus]
  );

  const handleBlur = React.useCallback(
    (e: React.FocusEvent<HTMLInputElement>) => {
      setIsFocused(false);
      onBlur?.(e);
    },
    [onBlur]
  );

  const handleChange = React.useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (!isHidden) {
        onChange?.(e);
        return;
      }

      const newDisplayValue = e.target.value;
      const oldLength = realValue.length;
      const newLength = newDisplayValue.length;

      let newRealValue: string;

      if (newLength === 0) {
        newRealValue = "";
      } else if (newLength > oldLength) {
        const addedChars = newDisplayValue
          .split("")
          .filter((char) => char !== MASK_CHARACTER)
          .join("");
        newRealValue =
          addedChars.length > 0 ? realValue + addedChars : realValue;
      } else if (newLength < oldLength) {
        const charsDeleted = oldLength - newLength;
        newRealValue = realValue.slice(0, -charsDeleted);
      } else {
        newRealValue = realValue;
      }

      // Synthetic event for Formik - only includes essential properties
      const syntheticEvent = {
        target: {
          name: e.target.name,
          value: newRealValue,
          type: "text",
        },
        currentTarget: {
          name: e.currentTarget.name,
          value: newRealValue,
          type: "text",
        },
        type: "change",
        persist: () => {},
      } as unknown as React.ChangeEvent<HTMLInputElement>;

      onChange?.(syntheticEvent);
    },
    [isHidden, realValue, onChange]
  );

  const showToggleButton = hasValue || isFocused;
  const isRevealed = isPasswordVisible && !effectiveNonRevealable;
  const toggleLabel = effectiveNonRevealable
    ? "Value cannot be revealed"
    : isPasswordVisible
      ? "Hide password"
      : "Show password";

  return (
    <InputTypeIn
      ref={ref}
      value={getDisplayValue()}
      onChange={handleChange}
      onFocus={handleFocus}
      onBlur={handleBlur}
      disabled={disabled}
      showClearButton={showClearButton}
      autoComplete="off"
      rightSection={
        showToggleButton ? (
          <IconButton
            icon={isRevealed ? SvgEye : SvgEyeClosed}
            disabled={disabled || effectiveNonRevealable}
            onClick={noProp(() => setIsPasswordVisible((v) => !v))}
            type="button"
            action={isRevealed}
            internal
            toolTipPosition="left"
            tooltipSize="sm"
            tooltip={toggleLabel}
            aria-label={toggleLabel}
          />
        ) : undefined
      }
      {...props}
    />
  );
});

export default PasswordInputTypeIn;
